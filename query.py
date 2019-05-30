from whoosh import index
from whoosh.qparser import QueryParser
from whoosh.qparser.dateparse import DateParserPlugin

from whoosh.sorting import FieldFacet

from config import config

from whoosh.classify import Bo1Model

from whoosh.searching import Results
from whoosh.searching import ResultsPage
from whoosh import sorting
from whoosh.qparser import WildcardPlugin, PrefixPlugin, RegexPlugin
from whoosh import scoring
from string import digits
from whoosh.sorting import ScoreAndTimeFacet, ScoreFacet
import jieba
class Query(object):

    def __init__(self):
        self.ix = index.open_dir(config.index_file_path)
        self.ix2 = index.open_dir(config.index2_file_path)
        # Instatiate a query parser
        self.qp = QueryParser("content", self.ix.schema)

        # Add the DateParserPlugin to the parser
        self.qp.add_plugin(DateParserPlugin())
        self.qp.add_plugin(WildcardPlugin())
        self.qp.add_plugin(PrefixPlugin())
        self.qp.add_plugin(RegexPlugin())

    ## 将search返回的结果解析成json格式，用于前端展示
    def _results_todata(self, results):
        data = {}
        if isinstance(results, Results):
            data["total"] = results.estimated_length()
        elif isinstance(results, ResultsPage):
            data['total'] = results.total
        result_list = []
        for result in results:
            item = {}
            for key in result.keys():
                item[key] = result.get(key)
            import re
            match_class = re.compile('class="match term[0-9]"')
            item['description'] = match_class.sub(" ", str(result.highlights('content'))) \
                .replace(" ", "").replace("\r\n", "").replace("\n", "")
            item['description'] = self.truncate_description(
                item['description'])
            item['docnum'] = result.docnum
            result_list.append(item)
        data["results"] = result_list
        return data

    def _results_tohotdata(self, results):
        from datetime import datetime, timedelta
        now = datetime.now()
        daySeconds = 86400
        weekSeconds = daySeconds * 7
        monthSecond = weekSeconds * 30
        data = {}
        if isinstance(results, Results):
            data["total"] = results.estimated_length()
        elif isinstance(results, ResultsPage):
            data['total'] = results.total
        result_list = []
        i = 0
        for result in results:
            i = i + 1
            item = {}
            for key in result.keys():
                item[key] = result.get(key)
            timespan = (now - item['publish_time']).seconds
            if timespan > daySeconds:
                if timespan < weekSeconds:
                    item['hotScore'] = result.score * 1
                else:
                    item['hotScore'] = result.score * 0.5
            else:
                item['hotScore'] = result.score * 1.5
            import re
            match_class = re.compile('class="match term[0-9]"')
            item['description'] = match_class.sub(" ", str(result.highlights('content'))) \
                .replace(" ", "").replace("\r\n", "").replace("\n", "")
            item['description'] = self.truncate_description(
                item['description'])
            item['docnum'] = result.docnum
            result_list.append(item)
            if i == 100:
                result_list = sorted(result_list, key=lambda results: results['hotScore'])
        if i < 100:
            result_list = sorted(result_list, key=lambda results: results['hotScore'])
        data["results"] = result_list
        return data

    ## 搜索功能，每次搜索一页
    def query_page(self, term, page_num, page_len, sort_type):

        with self.ix.searcher() as searcher:
            if sort_type == 1:  # default sorted
                results = searcher.search_page(self.qp.parse(
                    term), pagenum=page_num, pagelen=page_len,sortedby=ScoreFacet())
                #results2 = searcher.search_page(self.qp.parse(
                #    term), pagenum=page_num, pagelen=page_len, sortedby=ScoreAndTimeFacet())
                #self.generate_similarQuery(results,term)
            if sort_type == 2:  # sorted by custom hot value
                publish_time = FieldFacet("publish_time", reverse=True)
                results = searcher.search_page(self.qp.parse(
                    term), pagenum=page_num, pagelen=page_len, sortedby=publish_time)
            if sort_type == 3:  # sorted by time
                publish_time = FieldFacet("publish_time", reverse=True)
                results = searcher.search_page(self.qp.parse(
                    term), pagenum=page_num, pagelen=page_len, sortedby=ScoreAndTimeFacet())
            return self._results_todata(results), results.results.runtime

    ## 截断正文内容，避免过长
    def truncate_description(self, description):
        """
        Truncate description to fit in result format.
        """
        if len(description) <= 160:
            return description
        cut_desc = description[:160]
        i = 160
        letter = description[i]
        length = len(description)
        while i < length - 1 and not (letter == ',' or letter == '，' or letter == '.' or letter == '。'):
            cut_desc += letter
            i = i + 1
            letter = description[i]
        cut_desc += letter
        # print(cut_desc)
        return cut_desc

    # 计算句子的TF-IDF
    def cal_TF_IDF(self,words,countKey):
        with self.ix.searcher(weighting=scoring.TF_IDF()) as searcher_tfidf:
            #words = list(jieba.cut(sentence))
            count = 0
            score = 0
            for word in words:
                #if word == u'的' or word == u'地' or word == u'和':
                #    continue
                count += 1
                try:
                    tf = searcher_tfidf.term_info('content', word).max_weight()
                except:
                    tf = 0.1
                score += searcher_tfidf.idf('content',word) * tf
            if count == 0:
                return 0
            else:
                return countKey * score / count
    
    
    def sentenceFind(self,sentence,terms):
        for term in terms:
            if sentence.find(term) != -1 :
                return 1
        return 0
    # 在20个句子中 选取5个包含关键词的较高TF-IDF句子
    def generate_similarQuery(self, results, query_str):
        import re
        word_count = 0 # 句子数量
        keywords = []
        items = []
        similarQuery = []
        terms = []
        keywords = re.split(" ", query_str)
        for keyword in keywords:
            temps = list(jieba.cut(keyword))
            for temp in temps:
                if len(temp) == 0 :
                    continue
                terms.append(temp)
        for result in results[0:9]:
            content_count = 0
            content = result.get('content')
            content = content.replace(" ", ",")
            sentences = re.split(r"[,|.|，|。|!|！|?|？|:|：|；|;|……|、]", content)
            for sentence in sentences:
                item = {}
                countKey = 0
                #for keyword in keywords:
                for term in terms:
                    #terms = jieba.cut(keyword)
                    #self.sentenceFind(sentence,terms)
                    #if sentence.find(keyword) != -1:
                    #if self.sentenceFind(sentence,keyword) != 0:
                    if sentence.find(term) != -1:
                        countKey += 1
                        continue
                if countKey == 0:
                    continue
                pattern = re.compile(r'[^\u4e00-\u9fa5]')
                sentence_cn = re.sub(pattern, '', sentence)
                words = list(jieba.cut(sentence_cn))
                if len(words) > 8 or len(words) < 3:
                    continue
                #score = self.cal_TF_IDF(re.sub(pattern, '', words))
                score = self.cal_TF_IDF(words,countKey)
                item['sentence'] = sentence
                item['score'] = score
                items.append(item)
                word_count += 1
                content_count += 1
                if content_count > 2:   # 文章中有5个以上句子
                    break
                if word_count >= 30:    # 只挑选20个句子
                    break
            if word_count >= 30:
                break
        #items = list(set(items))
        items.sort(key=lambda temp : temp['score'],reverse=True)

        count = 0
        
        #SentenceFilter = ""
        last_score = 0
        for item in items:
            if count >= 5:
                continue
            if last_score == item["score"]:
                continue
            similarQuery.append(item["sentence"])
            count += 1
            last_score = item['score']
        return similarQuery






    ## 根据关键词生成snippet
    def generate_snippet_from_keyword(self, content, keywords):
        content = content.replace(" ", "")
        import re
        sentences = re.split(r"[,|.|，|。|!|！|?|？]", content)
        snippet = ""
        count = 0
        for sentence in sentences:
            for keyword in keywords:
                if sentence.find(keyword) > 0:
                    # print(keyword, sentence)
                    snippet = snippet + "," + sentence
                    keywords.remove(keyword)
                    break
            if len(keywords) == 0:
                return snippet[1:] + "。"
        return snippet[1:] + "。"

    def get_hot_words(self):
        import re
        keywords = []
        searchitem = ''
        word = ''
        reader = self.ix2.reader()
        sentences = list(reader.field_terms('content'))
        for sentence in sentences:
            words = re.split(r"0xffff",sentence)
            for word in words:
                searchitem = searchitem + word + ' '
            searchitem = searchitem.strip()
            keywords.append(searchitem)
            searchitem = ''
        return keywords
    ## 根据关键词生成推荐新闻，并生成摘要
    def recommend_news(self):
        data = {}
        total = 0
        result_list = []
        keywords = self.get_hot_words()
        data["results"] = result_list
        with self.ix.searcher() as searcher:
            for keyword in keywords:
                results = searcher.search(self.qp.parse(keyword), limit=1, sortedby='publish_time')
                # keywords = [keyword for keyword, score
                #             in results.key_terms("content", docs=10, numterms=5)]
                # print(keywords)
                item = {}
                for result in results:
                    total = total + 1
                    for key in result.keys():
                        item[key] = result.get(key)
                    item["keywords"] = [keyword[0] for keyword in searcher.key_terms([result.docnum], "content")]
                    item["snippet"] = self.generate_snippet_from_keyword(item['content'], item['keywords'])
                    print(item['snippet'])
                    result_list.append(item)
                    break
            data['total'] = total
            data['results'] = result_list
            return data

    def get_recommend_query(self, term):
        recom_query = []
        with self.ix.searcher() as searcher:
            results = searcher.search_page(
                self.qp.parse(term), pagenum=1, pagelen=10)
            recommends = self.generate_similarQuery(results, term)
            for recommend in recommends:
                item = {}
                item['term']  = recommend
                recom_query.append(item)
            # for result in results:
            #     #self.generate_similarQuery(results, term)
            #     item = {}
            #     item['term'] = result['title']
            #     recom_query.append(item)
        return recom_query

    def search_more_like_this(self, url, fieldname, top):
        with self.ix.searcher() as searcher:
            docnum = searcher.document_number(url=url)
            results = searcher.more_like(docnum, fieldname, text=None,
                                         top=top, numterms=5, model=Bo1Model,
                                         normalize=True, filter=None)

            return self._results_todata(results)


if __name__ == '__main__':
    query = Query()
    # print(query.query("测试", 1, 10))
    print(query.query_page(u"测试", 1, 10, 1))

    # query.query_page("测试",1,10, 1)
    # print(query.recommend_news())
    query.recommend_news()
