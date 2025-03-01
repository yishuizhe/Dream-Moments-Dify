"""
感情处理模块
负责处理感情相关功能，包括:
- 文本正负向识别
- 文本感情七维构建
- 文本感情强烈程度评分
"""
import pandas as pd
import jieba
from snownlp import SnowNLP
from collections import Counter

# 加载否定词表
def load_negative_words(file_path):
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return [line.strip() for line in f.readlines()]
    except FileNotFoundError:
        print(f"未找到否定词表文件: {file_path}")
        return []

NEGATIVE_WORDS = load_negative_words('src\handlers\emodata\否定词表.txt')

# 情感分类到情感类型和极性的映射关系
CATEGORY_MAPPING = {
    # 喜悦（正面）
    'PA': ('joy', 'positive'),
    'PE': ('joy', 'positive'),
    # 喜好（正面）
    'PD': ('like', 'positive'),
    'PH': ('like', 'positive'),
    'PG': ('like', 'positive'),
    'PB': ('like', 'positive'),
    'PK': ('like', 'positive'),
    # 惊讶（正面）
    'PC': ('surprise', 'positive'),
    # 愤怒（负面）
    'NA': ('anger', 'negative'),
    # 低落（负面）
    'NB': ('depress', 'negative'),
    'NJ': ('depress', 'negative'),
    'NH': ('depress', 'negative'),
    'PF': ('depress', 'negative'),
    # 恐惧（负面）
    'NI': ('fear', 'negative'),
    'NC': ('fear', 'negative'),
    'NG': ('fear', 'negative'),
    # 厌恶（负面）
    'NE': ('dislike', 'negative'),
    'ND': ('dislike', 'negative'),
    'NN': ('dislike', 'negative'),
    'NK': ('dislike', 'negative'),
    'NL': ('dislike', 'negative')
}

class SentimentAnalyzer:
    def __init__(self):
        self.emotion_dict = {}
        self._load_emotion_dictionary()

    def _load_emotion_dictionary(self):
        """加载情感词典并构建快速查询结构"""
        try:
            df = pd.read_excel(r'src\handlers\emodata\大连理工大学中文情感词汇本体.xlsx.xlsx')
            for _, row in df.iterrows():
                word = row['词语']
                category = row['情感分类']
                if category in CATEGORY_MAPPING:
                    emotion_type, polarity = CATEGORY_MAPPING[category]
                    self.emotion_dict[word] = (emotion_type, polarity)
            print('情感词典加载完成')
        except FileNotFoundError:
            print("未找到情感词典文件，请检查路径。")

    def _analyze_emotion(self, text):
        """核心情感分析方法"""
        counters = {
            'positive': 0,
            'negative': 0,
            'anger': 0,
            'dislike': 0,
            'fear': 0,
            'depress': 0,
            'surprise': 0,
            'like': 0,
            'joy': 0
        }

        # 分词
        words = jieba.lcut(text)

        # 处理否定词
        for i, word in enumerate(words):
            if word in NEGATIVE_WORDS and i < len(words) - 1:
                next_word = words[i + 1]
                if next_word in self.emotion_dict:
                    emotion_type, polarity = self.emotion_dict[next_word]
                    # 反转极性
                    new_polarity = 'negative' if polarity == 'positive' else 'positive'
                    self.emotion_dict[next_word] = (emotion_type, new_polarity)

        # 统计词频
        word_counts = Counter(words)

        # 情感计数处理
        for word, count in word_counts.items():
            if word in self.emotion_dict:
                emotion_type, polarity = self.emotion_dict[word]

                # 更新极性计数
                counters[polarity] += count

                # 更新具体情感计数
                if emotion_type in counters:
                    counters[emotion_type] += count

        # 确定情感极性
        if counters['positive'] > counters['negative']:
            polarity = '正面'
        elif counters['positive'] == counters['negative']:
            polarity = '中立'
        else:
            polarity = '负面'

        # 确定主要情感类型
        emotion_fields = ['anger', 'dislike', 'fear', 'depress', 'surprise', 'like', 'joy']
        emotion_values = [(field, counters[field]) for field in emotion_fields]
        main_emotion, max_count = max(emotion_values, key=lambda x: x[1])

        return {
            'sentiment_type': main_emotion.capitalize() if max_count > 0 else 'None',
            'polarity': polarity,
            'emotion_info': {
                'length': len(words),
                'positive': counters['positive'],
                'negative': counters['negative'],
                **{k: v for k, v in counters.items() if k not in ['positive', 'negative']}
            }
        }

    def _get_sentiment_score(self, text):
        """获取SnowNLP情感评分"""
        return SnowNLP(text).sentiments

    def analyze(self, text):
        '''综合分析方法'''
        emotion_result = self._analyze_emotion(text)
        raw_score = self._get_sentiment_score(text)

        # 根据极性调整符号位
        polarity = emotion_result['polarity']
        adjusted_score = raw_score
        if polarity == '正面':
            adjusted_score += 1
        elif polarity == '负面':
            adjusted_score -= 1

        return {
            **emotion_result,
            'sentiment_score': adjusted_score
        }

if __name__ == "__main__":
    analyzer = SentimentAnalyzer()
    test_text = "我不喜欢你"
    result = analyzer.analyze(test_text)
    print(result)
