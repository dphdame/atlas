"""
ATLAS - Automated Thematic Labeling and Analysis System
Topic Modeling Module

Uses traditional NLP (LDA) - no generative AI

This module handles:
- Text preprocessing
- LDA topic modeling
- Theme extraction and assignment
"""

import pandas as pd
import numpy as np
import re
from collections import Counter

# NLP imports
from sklearn.feature_extraction.text import CountVectorizer, TfidfVectorizer
from sklearn.decomposition import LatentDirichletAllocation
import nltk
from nltk.corpus import stopwords
from nltk.stem import WordNetLemmatizer
from nltk.tokenize import word_tokenize

# Spell checking
try:
    from spellchecker import SpellChecker
    SPELLCHECKER_AVAILABLE = True
except ImportError:
    SPELLCHECKER_AVAILABLE = False

# Lazy initialization of spell checker
_spell_checker = None

def get_spell_checker():
    """Lazy initialization of spell checker."""
    global _spell_checker
    if _spell_checker is None and SPELLCHECKER_AVAILABLE:
        _spell_checker = SpellChecker()
    return _spell_checker


def correct_spelling(text, level='off'):
    """
    Apply spelling correction based on level.

    Args:
        text: Input text string
        level: 'off', 'light', or 'strict'
            - off: No correction
            - light: Only fix words with edit distance 1 and high confidence
            - strict: Fix all detected misspellings

    Returns:
        Corrected text string
    """
    if level == 'off' or not text or not isinstance(text, str):
        return text

    if not SPELLCHECKER_AVAILABLE:
        return text

    spell = get_spell_checker()
    if spell is None:
        return text

    words = text.split()
    corrected = []

    for word in words:
        # Skip short words, numbers, and words with special characters
        clean_word = re.sub(r'[^a-zA-Z]', '', word)
        if len(clean_word) <= 2 or not clean_word.isalpha():
            corrected.append(word)
            continue

        word_lower = clean_word.lower()

        # Check if word is correctly spelled
        if word_lower in spell:
            corrected.append(word)
            continue

        # Get correction
        correction = spell.correction(word_lower)

        if correction is None or correction == word_lower:
            # No correction found
            corrected.append(word)
        elif level == 'light':
            # Only apply if it's an obvious typo (edit distance 1)
            candidates = spell.candidates(word_lower)
            if candidates and correction in candidates:
                # Check if it's a single-character fix
                if abs(len(correction) - len(word_lower)) <= 1:
                    # Preserve original case pattern
                    if word[0].isupper():
                        correction = correction.capitalize()
                    # Preserve any punctuation that was attached
                    if word != clean_word:
                        # Reconstruct with original punctuation
                        corrected.append(word.replace(clean_word, correction, 1))
                    else:
                        corrected.append(correction)
                else:
                    corrected.append(word)
            else:
                corrected.append(word)
        else:  # strict
            # Apply any correction found
            if word[0].isupper():
                correction = correction.capitalize()
            # Preserve any punctuation
            if word != clean_word:
                corrected.append(word.replace(clean_word, correction, 1))
            else:
                corrected.append(correction)

    return ' '.join(corrected)


def get_spelling_corrections_preview(texts, level='off'):
    """
    Get a preview of spelling corrections that would be applied.

    Args:
        texts: List or Series of text strings
        level: Spell check level ('off', 'light', 'strict')

    Returns:
        List of dicts with keys: original_word, correction, original_phrase
    """
    if level == 'off' or not SPELLCHECKER_AVAILABLE:
        return []

    spell = get_spell_checker()
    if spell is None:
        return []

    corrections = []
    seen_corrections = set()  # Avoid duplicates

    for text in texts:
        if not text or not isinstance(text, str):
            continue

        words = text.split()

        for i, word in enumerate(words):
            clean_word = re.sub(r'[^a-zA-Z]', '', word)
            if len(clean_word) <= 2 or not clean_word.isalpha():
                continue

            word_lower = clean_word.lower()

            if word_lower in spell:
                continue

            correction = spell.correction(word_lower)

            if correction is None or correction == word_lower:
                continue

            # Check if this correction would actually be applied at this level
            would_apply = False
            if level == 'strict':
                would_apply = True
            elif level == 'light':
                candidates = spell.candidates(word_lower)
                if candidates and correction in candidates:
                    if abs(len(correction) - len(word_lower)) <= 1:
                        would_apply = True

            if would_apply and (word_lower, correction) not in seen_corrections:
                seen_corrections.add((word_lower, correction))

                # Get surrounding context (5 words before and after)
                start = max(0, i - 5)
                end = min(len(words), i + 6)
                context_words = words[start:end]
                # Highlight the word in context
                word_pos = i - start
                if word_pos < len(context_words):
                    context_words[word_pos] = f"**{context_words[word_pos]}**"
                context = ' '.join(context_words)

                corrections.append({
                    'original_word': word_lower,
                    'correction': correction,
                    'original_phrase': context
                })

    return corrections


# Sentiment Analysis
_sentiment_analyzer = None

def get_sentiment_analyzer():
    """Lazy initialization of sentiment analyzer."""
    global _sentiment_analyzer
    if _sentiment_analyzer is None:
        try:
            nltk.data.find('sentiment/vader_lexicon.zip')
        except LookupError:
            nltk.download('vader_lexicon', quiet=True)
        from nltk.sentiment.vader import SentimentIntensityAnalyzer
        _sentiment_analyzer = SentimentIntensityAnalyzer()
    return _sentiment_analyzer


def analyze_sentiment(text):
    """
    Calculate sentiment score for text using VADER.

    Args:
        text: Input text string

    Returns:
        Compound sentiment score (-1.0 to 1.0)
        - Positive: > 0.05
        - Neutral: -0.05 to 0.05
        - Negative: < -0.05
    """
    if not text or not isinstance(text, str) or len(text.strip()) == 0:
        return 0.0

    sia = get_sentiment_analyzer()
    scores = sia.polarity_scores(text)
    return scores['compound']


def get_sentiment_label(score):
    """Convert sentiment score to human-readable label."""
    if score >= 0.05:
        return 'Positive'
    elif score <= -0.05:
        return 'Negative'
    else:
        return 'Neutral'


# Response Length Handling
def count_words(text):
    """Count words in text."""
    if not text or not isinstance(text, str):
        return 0
    # Split on whitespace and filter empty strings
    words = [w for w in text.split() if w.strip()]
    return len(words)


def check_response_length(text, min_words=5):
    """
    Check if response meets minimum length requirement.

    Args:
        text: Input text string
        min_words: Minimum word count (default: 5)

    Returns:
        Tuple of (word_count, meets_minimum, flag_message)
    """
    word_count = count_words(text)
    meets_minimum = word_count >= min_words

    if word_count == 0:
        flag = "Empty response"
    elif word_count < min_words:
        flag = f"Below minimum ({word_count}/{min_words} words)"
    else:
        flag = None

    return word_count, meets_minimum, flag


# Download required NLTK data (only needed once)
def setup_nltk():
    """Download required NLTK data files."""
    resources = [
        ('tokenizers/punkt', 'punkt'),
        ('tokenizers/punkt_tab', 'punkt_tab'),
        ('corpora/stopwords', 'stopwords'),
        ('corpora/wordnet', 'wordnet'),
        ('sentiment/vader_lexicon.zip', 'vader_lexicon')
    ]
    for path, name in resources:
        try:
            nltk.data.find(path)
        except LookupError:
            nltk.download(name, quiet=True)

# Custom stopwords for qualitative analysis
# These are common words that don't add meaning to theme analysis
ATLAS_STOPWORDS = {
    # Standard English stopwords
    'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for',
    'of', 'with', 'by', 'from', 'as', 'is', 'was', 'are', 'were', 'been',
    'be', 'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would',
    'could', 'should', 'may', 'might', 'must', 'shall', 'can', 'need',
    'dare', 'ought', 'used', 'it', 'its', 'this', 'that', 'these', 'those',
    'i', 'me', 'my', 'myself', 'we', 'our', 'ours', 'ourselves', 'you',
    'your', 'yours', 'yourself', 'yourselves', 'he', 'him', 'his', 'himself',
    'she', 'her', 'hers', 'herself', 'they', 'them', 'their', 'theirs',
    'themselves', 'what', 'which', 'who', 'whom', 'when', 'where', 'why',
    'how', 'all', 'each', 'every', 'both', 'few', 'more', 'most', 'other',
    'some', 'such', 'no', 'nor', 'not', 'only', 'own', 'same', 'so', 'than',
    'too', 'very', 's', 't', 'just', 'don', 'now', 've', 'll', 're', 'm',

    # Filler words and conversational terms
    'actually', 'basically', 'really', 'literally', 'definitely', 'probably',
    'maybe', 'perhaps', 'sometimes', 'always', 'never', 'often', 'usually',
    'also', 'get', 'got', 'like', 'thing', 'things', 'lot', 'lots',
    'going', 'go', 'went', 'come', 'came', 'make', 'made', 'still', 'even',
    'much', 'many', 'want', 'wanted', 'know', 'think', 'feel', 'said',
    'say', 'says', 'tell', 'told', 'ask', 'asked',

    # Time-related filler words
    'day', 'days', 'week', 'weeks', 'month', 'months', 'year', 'years',
    'time', 'times', 'today', 'yesterday', 'tomorrow', 'ago', 'later',
    'before', 'after', 'during', 'while', 'since', 'until', 'already',

    # Quantity fillers
    'one', 'two', 'three', 'first', 'second', 'last', 'next',
    'something', 'anything', 'nothing', 'everything', 'someone', 'anyone',
    'everyone', 'nobody', 'somewhere', 'anywhere', 'everywhere',

    # Conversational fillers
    'well', 'okay', 'ok', 'yes', 'no', 'yeah', 'yep', 'nope',
    'right', 'sure', 'guess', 'mean', 'means', 'kind', 'sort',
    'way', 'ways', 'back', 'around', 'through', 'into', 'onto',
    'upon', 'along', 'across', 'behind', 'between', 'among',

    # Common verbs that don't indicate themes
    'put', 'take', 'took', 'give', 'gave', 'given', 'keep', 'kept',
    'let', 'try', 'tried', 'start', 'started', 'stop', 'stopped',
    'see', 'saw', 'seen', 'look', 'looked', 'looking',
    'use', 'used', 'using', 'seem', 'seemed', 'seems',

    # Interview/survey context words
    'question', 'answer', 'response', 'interview', 'survey'
}


class ThematicAnalyzer:
    """
    Performs LDA-based thematic analysis on qualitative text data.
    Designed for focus group and open-ended survey responses.
    """

    def __init__(self, n_topics=5, max_features=1000, min_df=2, max_df=0.95,
                 custom_stopwords=None, spell_check='off'):
        """
        Initialize the analyzer.

        Args:
            n_topics: Number of topics/themes to extract
            max_features: Maximum vocabulary size
            min_df: Minimum document frequency for terms
            max_df: Maximum document frequency for terms (filter very common words)
            custom_stopwords: Additional words to ignore (list or set)
            spell_check: Spell check level ('off', 'light', 'strict')
        """
        self.n_topics = n_topics
        self.max_features = max_features
        self.min_df = min_df
        self.max_df = max_df
        self.spell_check = spell_check

        # Combine built-in stopwords with any custom ones
        self.stopwords = ATLAS_STOPWORDS.copy()
        if custom_stopwords:
            self.stopwords.update({w.lower().strip() for w in custom_stopwords})

        self.vectorizer = None
        self.lda_model = None
        self.feature_names = None
        self.topic_labels = None

        # Setup NLTK
        setup_nltk()
        self.lemmatizer = WordNetLemmatizer()

    def preprocess_text(self, text):
        """
        Clean and preprocess a single text response.

        Args:
            text: Raw text string

        Returns:
            Preprocessed text string
        """
        if pd.isna(text) or not isinstance(text, str):
            return ""

        # Apply spell check first (before lowercasing for case preservation)
        text = correct_spelling(text, self.spell_check)

        # Lowercase
        text = text.lower()

        # Remove special characters but keep spaces
        text = re.sub(r'[^a-z\s]', ' ', text)

        # Tokenize
        try:
            tokens = word_tokenize(text)
        except:
            tokens = text.split()

        # Remove stopwords and lemmatize
        processed_tokens = []
        for token in tokens:
            if len(token) > 2 and token not in self.stopwords:
                try:
                    lemma = self.lemmatizer.lemmatize(token)
                    processed_tokens.append(lemma)
                except:
                    processed_tokens.append(token)

        return ' '.join(processed_tokens)

    def fit(self, texts):
        """
        Fit the topic model on a collection of texts.

        Args:
            texts: List or Series of text responses

        Returns:
            self
        """
        # Preprocess all texts
        processed_texts = [self.preprocess_text(t) for t in texts]

        # Vectorize
        self.vectorizer = CountVectorizer(
            max_features=self.max_features,
            min_df=self.min_df,
            max_df=self.max_df,
            ngram_range=(1, 2)  # Include bigrams
        )

        doc_term_matrix = self.vectorizer.fit_transform(processed_texts)
        self.feature_names = self.vectorizer.get_feature_names_out()

        # Fit LDA
        self.lda_model = LatentDirichletAllocation(
            n_components=self.n_topics,
            max_iter=20,
            learning_method='online',
            random_state=42,
            n_jobs=-1
        )

        self.lda_model.fit(doc_term_matrix)

        # Generate default topic labels
        self._generate_topic_labels()

        return self

    def _generate_topic_labels(self, n_words=3):
        """Generate descriptive labels for each topic based on deduplicated top words."""
        deduplicated = self.get_topic_words(n_words=n_words)
        self.topic_labels = {}
        for topic_idx in range(self.n_topics):
            top_words = [w for w, _ in deduplicated.get(topic_idx, [])]
            self.topic_labels[topic_idx] = f"Topic {topic_idx + 1}: {', '.join(top_words)}"

    def get_topic_words(self, n_words=10):
        """
        Get the top words for each topic, with each word appearing in only
        the topic where it has the highest weight (no cross-topic duplicates).

        Args:
            n_words: Number of top words to return per topic

        Returns:
            Dict mapping topic index to list of (word, weight) tuples
        """
        # Step 1: For every word, find which topic gives it the highest weight
        word_best_topic = {}
        for topic_idx, topic in enumerate(self.lda_model.components_):
            for word_idx, weight in enumerate(topic):
                word = self.feature_names[word_idx]
                if word not in word_best_topic or weight > word_best_topic[word][1]:
                    word_best_topic[word] = (topic_idx, weight)

        # Step 2: For each topic, collect its "owned" words sorted by weight
        topic_words = {}
        for topic_idx, topic in enumerate(self.lda_model.components_):
            owned_words = []
            sorted_indices = topic.argsort()[::-1]
            for i in sorted_indices:
                word = self.feature_names[i]
                if word_best_topic.get(word, (None,))[0] == topic_idx:
                    owned_words.append((word, topic[i]))
                    if len(owned_words) >= n_words:
                        break
            topic_words[topic_idx] = owned_words

        return topic_words

    def transform(self, texts):
        """
        Get topic distributions for new texts.

        Args:
            texts: List or Series of text responses

        Returns:
            numpy array of shape (n_docs, n_topics) with topic probabilities
        """
        processed_texts = [self.preprocess_text(t) for t in texts]
        doc_term_matrix = self.vectorizer.transform(processed_texts)
        return self.lda_model.transform(doc_term_matrix)

    def fit_transform(self, texts):
        """Fit the model and return topic distributions."""
        self.fit(texts)
        return self.transform(texts)

    def assign_topics(self, texts, n_themes=1, threshold=0.1):
        """
        Assign themes to each text.

        Args:
            texts: List or Series of text responses
            n_themes: Number of themes to assign (1-3)
            threshold: Minimum probability to assign a theme

        Returns:
            DataFrame with theme assignments
        """
        topic_distributions = self.transform(texts)

        results = []
        for idx, dist in enumerate(topic_distributions):
            # Sort topics by probability (descending)
            sorted_indices = np.argsort(dist)[::-1]

            row = {}

            # Assign up to n_themes
            for rank, label in enumerate(['primary', 'secondary', 'tertiary']):
                if rank < n_themes and rank < len(sorted_indices):
                    topic_idx = sorted_indices[rank]
                    prob = dist[topic_idx]

                    if prob >= threshold or rank == 0:  # Always assign primary
                        row[f'{label}_theme'] = self.topic_labels[topic_idx]
                        row[f'{label}_theme_idx'] = int(topic_idx)
                        row[f'{label}_fit'] = float(prob)
                    else:
                        row[f'{label}_theme'] = None
                        row[f'{label}_theme_idx'] = None
                        row[f'{label}_fit'] = None
                else:
                    row[f'{label}_theme'] = None
                    row[f'{label}_theme_idx'] = None
                    row[f'{label}_fit'] = None

            # Store full distribution for reference
            row['topic_distribution'] = dist.tolist()

            results.append(row)

        return pd.DataFrame(results)

    def analyze_dataframe(self, df, text_column='response', n_themes=1,
                          include_sentiment=True, min_words=5):
        """
        Run full analysis on a DataFrame.

        Args:
            df: DataFrame with text responses
            text_column: Name of column containing text
            n_themes: Number of themes to assign (1-3)
            include_sentiment: Whether to calculate sentiment scores
            min_words: Minimum word count for analysis (0 to disable)

        Returns:
            DataFrame with original data plus topic assignments
        """
        result = df.copy()

        # Add length metrics first
        length_data = df[text_column].apply(lambda x: check_response_length(x, min_words))
        result['word_count'] = length_data.apply(lambda x: x[0])
        result['meets_length_min'] = length_data.apply(lambda x: x[1])
        result['length_flag'] = length_data.apply(lambda x: x[2])

        # Store processed text for word cloud (after spell check and preprocessing)
        result['_processed_text'] = df[text_column].apply(self.preprocess_text)

        # Fit and get assignments
        self.fit(df[text_column])
        assignments = self.assign_topics(df[text_column], n_themes=n_themes)

        # Add theme columns
        for col in ['primary_theme', 'primary_theme_idx', 'primary_fit',
                    'secondary_theme', 'secondary_theme_idx', 'secondary_fit',
                    'tertiary_theme', 'tertiary_theme_idx', 'tertiary_fit']:
            if col in assignments.columns:
                result[col] = assignments[col]

        # Override theme for responses below minimum length
        if min_words > 0:
            below_min_mask = ~result['meets_length_min']
            result.loc[below_min_mask, 'primary_theme'] = 'Below minimum length'
            result.loc[below_min_mask, 'primary_theme_idx'] = -2
            result.loc[below_min_mask, 'primary_fit'] = None
            if n_themes >= 2:
                result.loc[below_min_mask, 'secondary_theme'] = None
                result.loc[below_min_mask, 'secondary_theme_idx'] = None
                result.loc[below_min_mask, 'secondary_fit'] = None
            if n_themes >= 3:
                result.loc[below_min_mask, 'tertiary_theme'] = None
                result.loc[below_min_mask, 'tertiary_theme_idx'] = None
                result.loc[below_min_mask, 'tertiary_fit'] = None

        # Backward compatibility aliases
        result['dominant_topic'] = result['primary_theme_idx']
        result['topic_label'] = result['primary_theme']
        result['topic_probability'] = result['primary_fit']

        # Add sentiment analysis
        if include_sentiment:
            result['sentiment_score'] = df[text_column].apply(analyze_sentiment)
            result['sentiment_label'] = result['sentiment_score'].apply(get_sentiment_label)

        return result


# Default theme dictionary organized by Social Determinants of Health.
# Themes map to the five SDOH domains in the Healthy People 2030 framework:
#   Economic Stability, Education Access & Quality, Health Care Access & Quality,
#   Neighborhood & Built Environment, Social & Community Context.
DEFAULT_THEME_DICTIONARY = {
    # Economic Stability
    "Employment & Income": [
        "job", "jobs", "work", "working", "employed", "employment", "unemployed", "hire",
        "hired", "interview", "interviews", "resume", "career", "wage", "wages", "salary",
        "hours", "boss", "employer", "income", "earn", "earning", "paycheck", "gig"
    ],
    "Financial Stability": [
        "bills", "bill", "debt", "owe", "credit", "savings", "save", "saved", "saving",
        "bank", "account", "afford", "budget", "budgeting", "utilities", "electric",
        "phone", "internet", "taxes", "poverty", "broke"
    ],
    "Food Security": [
        "food", "groceries", "grocery", "eat", "eating", "meal", "meals", "hungry", "hunger",
        "snap", "foodbank", "pantry", "nutrition", "cook", "cooking", "kitchen", "wic",
        "produce", "fruits", "vegetables"
    ],
    # Education Access & Quality
    "Education & Training": [
        "school", "education", "class", "classes", "college", "university", "degree",
        "ged", "diploma", "training", "certificate", "certification", "learn", "learning",
        "study", "studying", "student", "teacher", "tutor", "graduate", "graduation",
        "literacy", "reading"
    ],
    # Health Care Access & Quality
    "Healthcare Access": [
        "health", "healthcare", "doctor", "medical", "medicine", "medication", "medications",
        "hospital", "clinic", "insurance", "prescription", "sick", "illness", "dental",
        "dentist", "vision", "glasses", "treatment", "medicaid", "medicare", "uninsured",
        "appointment", "checkup", "preventive", "screening"
    ],
    "Mental Health": [
        "stress", "stressed", "anxiety", "anxious", "depression", "depressed", "mental",
        "therapy", "therapist", "counseling", "counselor", "overwhelmed", "worried", "worry",
        "sleep", "sleeping", "hopeful", "hope", "hopeless", "calm", "peace", "peaceful",
        "trauma", "ptsd", "burnout"
    ],
    # Neighborhood & Built Environment
    "Housing": [
        "rent", "housing", "apartment", "home", "house", "landlord", "eviction", "evicted",
        "homeless", "shelter", "lease", "deposit", "roommate", "couch", "stable", "unstable",
        "move", "moved", "moving", "live", "living", "stay", "staying", "place", "room",
        "mold", "repair", "repairs", "overcrowded"
    ],
    "Transportation": [
        "car", "bus", "transit", "transportation", "drive", "driving", "license", "gas",
        "commute", "commuting", "ride", "uber", "lyft", "bike", "walk", "walking",
        "subway", "train", "sidewalk"
    ],
    # Social & Community Context
    "Family & Caregiving": [
        "child", "children", "kids", "kid", "baby", "infant", "toddler", "daycare",
        "childcare", "babysitter", "parent", "parenting", "mother", "father", "mom", "dad",
        "family", "son", "daughter", "diaper", "formula", "elderly", "caregiver", "caregiving"
    ],
    "Community & Safety": [
        "neighborhood", "community", "neighbor", "neighbors", "safe", "safety", "unsafe",
        "violence", "crime", "police", "church", "faith", "friend", "friends", "support",
        "isolated", "lonely", "discrimination", "racism", "language", "culture", "belonging"
    ]
}


class DictionaryAnalyzer:
    """
    Dictionary-based thematic analysis.
    Assigns themes based on keyword matches rather than statistical modeling.
    """

    def __init__(self, theme_dictionary=None, custom_stopwords=None, spell_check='off'):
        """
        Initialize the analyzer.

        Args:
            theme_dictionary: Dict mapping theme names to lists of keywords
            custom_stopwords: Additional words to ignore (not used in matching, just for display)
            spell_check: Spell check level ('off', 'light', 'strict')
        """
        self.theme_dictionary = theme_dictionary or DEFAULT_THEME_DICTIONARY
        self.topic_labels = {i: name for i, name in enumerate(self.theme_dictionary.keys())}
        self.n_topics = len(self.theme_dictionary)
        self.spell_check = spell_check

        # Setup NLTK for preprocessing
        setup_nltk()
        self.lemmatizer = WordNetLemmatizer()

    def preprocess_text(self, text):
        """Clean and preprocess text for matching."""
        if pd.isna(text) or not isinstance(text, str):
            return ""

        # Apply spell check first (before lowercasing for case preservation)
        text = correct_spelling(text, self.spell_check)

        text = text.lower()
        text = re.sub(r'[^a-z\s]', ' ', text)

        try:
            tokens = word_tokenize(text)
        except:
            tokens = text.split()

        # Lemmatize tokens
        processed = []
        for token in tokens:
            if len(token) > 2:
                try:
                    processed.append(self.lemmatizer.lemmatize(token))
                except:
                    processed.append(token)

        return ' '.join(processed)

    def score_themes(self, text):
        """
        Score each theme based on keyword matches in the text.

        Returns:
            Tuple of (scores_dict, matched_words_dict, percentages_dict)
        """
        processed = self.preprocess_text(text)
        words = set(processed.split())

        scores = {}
        matched_words = {}
        percentages = {}

        for theme, keywords in self.theme_dictionary.items():
            keyword_set = set(keywords)
            matches = words.intersection(keyword_set)
            scores[theme] = len(matches)
            matched_words[theme] = list(matches)
            percentages[theme] = len(matches) / len(keyword_set) if keyword_set else 0.0

        return scores, matched_words, percentages

    def assign_themes(self, texts, n_themes=1):
        """
        Assign themes to each text based on keyword matches.

        Args:
            texts: List or Series of text responses
            n_themes: Number of themes to assign (1-3)

        Returns:
            DataFrame with theme assignments
        """
        theme_names = list(self.theme_dictionary.keys())
        results = []

        for text in texts:
            scores, matched_words, percentages = self.score_themes(text)

            # Sort themes by score (descending)
            sorted_themes = sorted(scores.items(), key=lambda x: x[1], reverse=True)

            row = {}

            for rank, label in enumerate(['primary', 'secondary', 'tertiary']):
                if rank < n_themes and rank < len(sorted_themes):
                    theme, score = sorted_themes[rank]

                    if score > 0 or rank == 0:  # Always assign primary
                        theme_idx = theme_names.index(theme) if theme in theme_names else -1
                        row[f'{label}_theme'] = theme if score > 0 else 'Uncategorized'
                        row[f'{label}_theme_idx'] = theme_idx if score > 0 else -1
                        row[f'{label}_fit_count'] = score
                        row[f'{label}_fit_pct'] = percentages.get(theme, 0.0)
                        row[f'{label}_keywords'] = matched_words.get(theme, [])
                    else:
                        row[f'{label}_theme'] = None
                        row[f'{label}_theme_idx'] = None
                        row[f'{label}_fit_count'] = None
                        row[f'{label}_fit_pct'] = None
                        row[f'{label}_keywords'] = None
                else:
                    row[f'{label}_theme'] = None
                    row[f'{label}_theme_idx'] = None
                    row[f'{label}_fit_count'] = None
                    row[f'{label}_fit_pct'] = None
                    row[f'{label}_keywords'] = None

            # Store all matches for reference
            row['all_themes'] = [t for t, s in sorted_themes if s > 0]
            row['all_matched_keywords'] = {t: matched_words[t] for t, s in sorted_themes if s > 0}

            results.append(row)

        return pd.DataFrame(results)

    def get_topic_words(self, n_words=10):
        """Return the dictionary keywords for each theme."""
        topic_words = {}
        for idx, (theme, keywords) in enumerate(self.theme_dictionary.items()):
            # Return keywords with dummy weights (all equal)
            topic_words[idx] = [(word, 1.0) for word in keywords[:n_words]]
        return topic_words

    def analyze_dataframe(self, df, text_column='response', n_themes=1,
                          include_sentiment=True, min_words=5):
        """
        Run dictionary-based analysis on a DataFrame.

        Args:
            df: DataFrame with text responses
            text_column: Name of column containing text
            n_themes: Number of themes to assign (1-3)
            include_sentiment: Whether to calculate sentiment scores
            min_words: Minimum word count for analysis (0 to disable)

        Returns:
            DataFrame with original data plus theme assignments
        """
        result = df.copy()

        # Add length metrics first
        length_data = df[text_column].apply(lambda x: check_response_length(x, min_words))
        result['word_count'] = length_data.apply(lambda x: x[0])
        result['meets_length_min'] = length_data.apply(lambda x: x[1])
        result['length_flag'] = length_data.apply(lambda x: x[2])

        # Store processed text for word cloud (after spell check and preprocessing)
        result['_processed_text'] = df[text_column].apply(self.preprocess_text)

        # Get theme assignments
        assignments = self.assign_themes(df[text_column], n_themes=n_themes)

        # Add theme columns
        for col in ['primary_theme', 'primary_theme_idx', 'primary_fit_count', 'primary_fit_pct', 'primary_keywords',
                    'secondary_theme', 'secondary_theme_idx', 'secondary_fit_count', 'secondary_fit_pct', 'secondary_keywords',
                    'tertiary_theme', 'tertiary_theme_idx', 'tertiary_fit_count', 'tertiary_fit_pct', 'tertiary_keywords',
                    'all_themes', 'all_matched_keywords']:
            if col in assignments.columns:
                result[col] = assignments[col]

        # Override theme for responses below minimum length
        if min_words > 0:
            below_min_mask = ~result['meets_length_min']
            result.loc[below_min_mask, 'primary_theme'] = 'Below minimum length'
            result.loc[below_min_mask, 'primary_theme_idx'] = -2
            result.loc[below_min_mask, 'primary_fit_count'] = None
            result.loc[below_min_mask, 'primary_fit_pct'] = None
            result.loc[below_min_mask, 'primary_keywords'] = None
            if n_themes >= 2:
                result.loc[below_min_mask, 'secondary_theme'] = None
                result.loc[below_min_mask, 'secondary_theme_idx'] = None
                result.loc[below_min_mask, 'secondary_fit_count'] = None
                result.loc[below_min_mask, 'secondary_fit_pct'] = None
                result.loc[below_min_mask, 'secondary_keywords'] = None
            if n_themes >= 3:
                result.loc[below_min_mask, 'tertiary_theme'] = None
                result.loc[below_min_mask, 'tertiary_theme_idx'] = None
                result.loc[below_min_mask, 'tertiary_fit_count'] = None
                result.loc[below_min_mask, 'tertiary_fit_pct'] = None
                result.loc[below_min_mask, 'tertiary_keywords'] = None

        # Backward compatibility aliases
        result['dominant_topic'] = result['primary_theme_idx']
        result['topic_label'] = result['primary_theme']
        result['topic_probability'] = result['primary_fit_count']

        # Add sentiment analysis
        if include_sentiment:
            result['sentiment_score'] = df[text_column].apply(analyze_sentiment)
            result['sentiment_label'] = result['sentiment_score'].apply(get_sentiment_label)

        return result


def run_analysis(input_file, output_file=None, n_topics=5, text_column='response'):
    """
    Run thematic analysis on a CSV/Excel file.

    Args:
        input_file: Path to input CSV or Excel file
        output_file: Path to save results (optional)
        n_topics: Number of topics to extract
        text_column: Name of column containing text responses

    Returns:
        Tuple of (analyzed DataFrame, ThematicAnalyzer instance)
    """
    # Load data
    if input_file.endswith('.xlsx') or input_file.endswith('.xls'):
        df = pd.read_excel(input_file)
    else:
        df = pd.read_csv(input_file)

    print(f"Loaded {len(df)} responses from {input_file}")

    # Run analysis
    analyzer = ThematicAnalyzer(n_topics=n_topics)
    results = analyzer.analyze_dataframe(df, text_column=text_column)

    # Print topic summary
    print(f"\n{'='*60}")
    print(f"TOPIC SUMMARY ({n_topics} topics extracted)")
    print('='*60)

    topic_words = analyzer.get_topic_words(n_words=8)
    for topic_idx, words in topic_words.items():
        print(f"\n{analyzer.topic_labels[topic_idx]}")
        print(f"  Top words: {', '.join([w for w, _ in words])}")
        count = (results['dominant_topic'] == topic_idx).sum()
        print(f"  Responses: {count} ({count/len(results)*100:.1f}%)")

    # Save if output file specified
    if output_file:
        if output_file.endswith('.xlsx'):
            results.to_excel(output_file, index=False)
        else:
            results.to_csv(output_file, index=False)
        print(f"\nResults saved to {output_file}")

    return results, analyzer


if __name__ == "__main__":
    import sys

    # Default paths
    input_file = "data/sample_responses.csv"
    output_file = "output/analyzed_responses.csv"

    # Allow command line override
    if len(sys.argv) > 1:
        input_file = sys.argv[1]
    if len(sys.argv) > 2:
        output_file = sys.argv[2]

    results, analyzer = run_analysis(input_file, output_file, n_topics=5)
