"""
ATLAS - Automated Thematic Labeling and Analysis System
Qualitative Analysis Dashboard

Run with: streamlit run app.py
"""

import streamlit as st
import pandas as pd
import numpy as np
import re
import plotly.express as px
import plotly.graph_objects as go
from wordcloud import WordCloud
import matplotlib.pyplot as plt
from io import BytesIO
import os

from topic_modeling import (
    ThematicAnalyzer, DictionaryAnalyzer, DEFAULT_THEME_DICTIONARY,
    run_analysis, analyze_sentiment, get_sentiment_label,
    get_spelling_corrections_preview
)

# Page config
st.set_page_config(
    page_title="ATLAS Dashboard",
    page_icon="📊",
    layout="wide"
)

# Custom CSS
st.markdown("""
<style>
    /* Wider sidebar */
    [data-testid="stSidebar"] {
        min-width: 350px;
        max-width: 400px;
    }
    .main-header {
        font-size: 2.5rem;
        font-weight: 700;
        color: #005088;
        margin-bottom: 0.5rem;
    }
    .sub-header {
        font-size: 1.1rem;
        color: #64748b;
        margin-bottom: 2rem;
    }
    .metric-card {
        background-color: #f8fafc;
        border-radius: 10px;
        padding: 1rem;
        border-left: 4px solid #11caa0;
    }
    .topic-box {
        background-color: #f0fdf4;
        border-radius: 8px;
        padding: 1rem;
        margin: 0.5rem 0;
        border: 1px solid #11caa0;
    }
</style>
""", unsafe_allow_html=True)


def generate_wordcloud(text_series):
    """Generate a word cloud from text data."""
    text = ' '.join(text_series.dropna().astype(str))

    if not text.strip():
        return None

    wordcloud = WordCloud(
        width=800,
        height=400,
        background_color='white',
        colormap='viridis',
        max_words=100
    ).generate(text)

    fig, ax = plt.subplots(figsize=(10, 5))
    ax.imshow(wordcloud, interpolation='bilinear')
    ax.axis('off')

    return fig


def create_topic_distribution_chart(results, analyzer):
    """Create a bar chart of topic distributions."""
    topic_counts = results['dominant_topic'].value_counts().sort_index()

    # Handle both LDA (Topic 1: words) and Dictionary (theme name) formats
    # Map special indices to their display names
    special_labels = {-1: "Uncategorized", -2: "Below minimum length"}

    labels = []
    for i in topic_counts.index:
        if i in special_labels:
            labels.append(special_labels[i])
        elif i in analyzer.topic_labels:
            label = analyzer.topic_labels[i]
            # For LDA labels like "Topic 1: housing, rent, apartment",
            # keep the descriptive words and strip the "Topic N:" prefix
            if label.startswith("Topic ") and ':' in label:
                label = label.split(':', 1)[1].strip()
            labels.append(label)
        else:
            labels.append(f"Topic {i}")

    # Extended color palette for more topics
    colors = ['#005088', '#11caa0', '#f59e0b', '#e11d48', '#8b5cf6',
              '#06b6d4', '#84cc16', '#f97316', '#ec4899', '#6366f1']

    fig = go.Figure(data=[
        go.Bar(
            x=labels,
            y=topic_counts.values,
            marker_color=colors[:len(labels)],
            text=topic_counts.values,
            textposition='auto'
        )
    ])

    fig.update_layout(
        title="Responses by Theme",
        xaxis_title="Theme",
        yaxis_title="Number of Responses",
        showlegend=False,
        height=400,
        xaxis_tickangle=-45
    )

    return fig


def create_stratifier_topic_heatmap(results, stratifier_col, stratifier_label="Group"):
    """Create a heatmap of topics by stratifier (e.g., site, cohort, group)."""
    if stratifier_col not in results.columns:
        return None

    pivot = pd.crosstab(results[stratifier_col], results['topic_label'], normalize='index') * 100

    fig = px.imshow(
        pivot,
        labels=dict(x="Topic", y=stratifier_label, color="% of Responses"),
        aspect="auto",
        color_continuous_scale="Greens"
    )

    fig.update_layout(
        title=f"Topic Distribution by {stratifier_label}",
        height=300
    )

    return fig


def create_sentiment_distribution_chart(results):
    """Create histogram of sentiment scores."""
    if 'sentiment_score' not in results.columns:
        return None

    fig = px.histogram(
        results,
        x='sentiment_score',
        nbins=20,
        color_discrete_sequence=['#005088'],
        labels={'sentiment_score': 'Sentiment Score'}
    )

    fig.update_layout(
        title="Sentiment Distribution",
        xaxis_title="Sentiment Score (-1 = Negative, +1 = Positive)",
        yaxis_title="Number of Responses",
        height=300
    )

    # Add reference lines for neutral zone
    fig.add_vline(x=-0.05, line_dash="dash", line_color="gray", opacity=0.5)
    fig.add_vline(x=0.05, line_dash="dash", line_color="gray", opacity=0.5)

    return fig


def main():
    # Header
    st.markdown('<p class="main-header">ATLAS Dashboard</p>', unsafe_allow_html=True)
    st.markdown('<p class="sub-header">Thematic analysis of focus group and survey responses using traditional NLP (LDA topic modeling)</p>', unsafe_allow_html=True)

    # Sidebar for configuration
    st.sidebar.header("Configuration")

    # File upload
    uploaded_file = st.sidebar.file_uploader(
        "Upload your data (CSV or Excel)",
        type=['csv', 'xlsx', 'xls']
    )

    # Get locked params if they exist (from previous analysis)
    locked_params = st.session_state.get('locked_params', {})
    has_results = 'results' in st.session_state

    # Analysis parameters section - ALWAYS editable, use previous values as defaults
    st.sidebar.subheader("🔬 Analysis Settings")

    # Analysis mode - use locked value as default if available
    default_mode_idx = 0 if locked_params.get('analysis_mode', 'Guided (Dictionary)') == 'Guided (Dictionary)' else 1
    analysis_mode = st.sidebar.radio(
        "Analysis Mode",
        ["Guided (Dictionary)", "Automatic (LDA)"],
        index=default_mode_idx,
        help="**Guided**: Uses predefined themes organized by Social Determinants of Health (Healthy People 2030).\n\n**Automatic**: Algorithm discovers themes from word patterns."
    )

    # Text column selection
    text_column = st.sidebar.text_input(
        "Text column name",
        value=locked_params.get('text_column', 'response')
    )

    # Group column selection (optional - for grouping/filtering)
    stratifier_column = st.sidebar.text_input(
        "Group column (optional)",
        value=locked_params.get('stratifier_column', ''),
        help="Stratifying variable: column for grouping results (e.g., 'site', 'cohort', 'group'). Leave blank if not needed."
    )

    # Display label for the grouping variable
    stratifier_display_label = st.sidebar.text_input(
        "Group label",
        value=locked_params.get('stratifier_display_label', 'Group'),
        help="How the grouping variable appears in charts and tables (e.g., 'Group', 'Site', 'Cohort')."
    ) if stratifier_column else 'Group'

    # Theme assignment options
    default_themes_idx = locked_params.get('n_themes', 1) - 1
    n_themes = st.sidebar.radio(
        "Themes per response",
        [1, 2, 3],
        index=default_themes_idx,
        help="How many themes to assign to each response.\n\n"
             "**1**: Single best-fit theme\n\n"
             "**2**: Primary + secondary themes\n\n"
             "**3**: Primary + secondary + tertiary themes"
    )

    # Text preprocessing options
    spell_options = ["Off", "Light", "Strict"]
    default_spell = locked_params.get('spell_check', 'Off')
    default_spell_idx = spell_options.index(default_spell) if default_spell in spell_options else 0
    spell_check = st.sidebar.radio(
        "Spell check",
        spell_options,
        index=default_spell_idx,
        help="**Off**: Preserve original text (recommended for preserving dialect/slang)\n\n"
             "**Light**: Fix obvious typos only (e.g., 'teh' → 'the')\n\n"
             "**Strict**: Fix all detected misspellings"
    )
    spell_check_level = spell_check.lower()

    # Minimum response length
    min_words = st.sidebar.number_input(
        "Minimum words",
        min_value=0,
        max_value=50,
        value=locked_params.get('min_words', 5),
        help="Responses with fewer words will be flagged as 'Below minimum length'. Set to 0 to disable."
    )

    # Sentiment analysis
    include_sentiment = st.sidebar.checkbox(
        "Include sentiment analysis",
        value=locked_params.get('include_sentiment', True),
        help="Calculate sentiment score (-1 to +1) for each response using VADER."
    )

    custom_stopwords = locked_params.get('custom_stopwords', [])

    st.sidebar.divider()

    # Check if current settings differ from analyzed settings
    def settings_changed():
        if not has_results or not locked_params:
            return False
        return (
            analysis_mode != locked_params.get('analysis_mode') or
            text_column != locked_params.get('text_column') or
            stratifier_column != locked_params.get('stratifier_column', '') or
            stratifier_display_label != locked_params.get('stratifier_display_label', 'Group') or
            n_themes != locked_params.get('n_themes') or
            spell_check != locked_params.get('spell_check') or
            min_words != locked_params.get('min_words') or
            include_sentiment != locked_params.get('include_sentiment')
        )

    settings_modified = settings_changed()

    # Mode-specific options (always editable)
    if analysis_mode == "Automatic (LDA)":
        n_topics = st.sidebar.slider(
            "Number of topics",
            min_value=3,
            max_value=10,
            value=locked_params.get('n_topics', 5)
        )

        # Custom stopwords
        st.sidebar.subheader("Words to Ignore")
        custom_stopwords_input = st.sidebar.text_area(
            "Add words to ignore (one per line)",
            value='\n'.join(locked_params.get('custom_stopwords', [])),
            placeholder="Enter words like:\nactually\nbasically\nwhatever",
            height=100,
            help="These words will be excluded from the analysis. Common filler words are already excluded by default."
        )

        # Parse custom stopwords
        if custom_stopwords_input:
            custom_stopwords = [w.strip().lower() for w in custom_stopwords_input.split('\n') if w.strip()]
    else:
        # Initialize theme list in session state if not exists
        if 'theme_list' not in st.session_state:
            st.session_state['theme_list'] = list(DEFAULT_THEME_DICTIONARY.keys())
            st.session_state['edited_themes'] = {
                theme: ', '.join(keywords)
                for theme, keywords in DEFAULT_THEME_DICTIONARY.items()
            }

        # Editable theme dictionary
        with st.sidebar.expander("View/Edit Themes"):
            st.markdown("**Edit keywords for each theme** (comma-separated):")

            # Edit existing themes
            edited_themes = {}
            themes_to_remove = []

            for theme in st.session_state['theme_list']:
                col1, col2 = st.columns([5, 1])

                with col1:
                    default_val = st.session_state['edited_themes'].get(
                        theme,
                        ', '.join(DEFAULT_THEME_DICTIONARY.get(theme, []))
                    )
                    edited = st.text_area(
                        theme,
                        value=default_val,
                        height=68,
                        key=f"theme_{theme}"
                    )
                    # Parse back to list
                    keywords = [w.strip().lower() for w in edited.split(',') if w.strip()]
                    if keywords:  # Only include if has keywords
                        edited_themes[theme] = keywords
                    st.session_state['edited_themes'][theme] = edited

                with col2:
                    st.write("")  # Spacing for alignment
                    st.write("")
                    if st.button("🗑️", key=f"delete_{theme}", help=f"Delete {theme}"):
                        themes_to_remove.append(theme)

            # Process deletions
            if themes_to_remove:
                for theme in themes_to_remove:
                    st.session_state['theme_list'].remove(theme)
                    if theme in st.session_state['edited_themes']:
                        del st.session_state['edited_themes'][theme]
                st.rerun()

            # Store for use in analysis
            st.session_state['custom_theme_dict'] = edited_themes

            st.divider()

            # Add new theme (at the bottom)
            col1, col2 = st.columns([3, 1])
            with col1:
                new_theme_name = st.text_input("New theme name", key="new_theme_input", placeholder="e.g., Social Support")
            with col2:
                st.write("")  # Spacing
                if st.button("➕ Add", key="add_theme_btn"):
                    if new_theme_name and new_theme_name not in st.session_state['theme_list']:
                        st.session_state['theme_list'].append(new_theme_name)
                        st.session_state['edited_themes'][new_theme_name] = ""
                        st.rerun()

        n_topics = len(st.session_state.get('custom_theme_dict', DEFAULT_THEME_DICTIONARY))

    # Run Analysis button - always available, label changes based on state
    st.sidebar.divider()
    if has_results and settings_modified:
        st.sidebar.warning("⚠️ Settings changed from last analysis")
        run_analysis_btn = st.sidebar.button("🔄 Update Results", type="primary")
    elif has_results:
        run_analysis_btn = st.sidebar.button("🔄 Re-run Analysis", type="secondary")
    else:
        run_analysis_btn = st.sidebar.button("🔍 Run Analysis", type="primary")

    # Load data
    df = None

    if uploaded_file:
        try:
            if uploaded_file.name.endswith('.csv'):
                df = pd.read_csv(uploaded_file)
            else:
                df = pd.read_excel(uploaded_file)
            st.sidebar.success(f"Loaded {len(df)} rows")
        except Exception as e:
            st.sidebar.error(f"Error loading file: {e}")


    if df is None:
        if run_analysis_btn:
            st.sidebar.error("Please upload a file first")

        st.info("👆 Upload a CSV or Excel file with qualitative responses using the sidebar.")

        st.markdown("""
        ### Expected Data Format

        Your file should have at minimum a column with text responses. Example:

        | response_id | participant_id | site | question | response |
        |-------------|----------------|------|----------|----------|
        | 1 | P001 | North Clinic | What has helped your health... | Being able to walk to the clinic... |

        The tool will automatically identify themes across all responses.
        """)
        return

    # Validate text column exists
    if text_column not in df.columns:
        st.error(f"Column '{text_column}' not found. Available columns: {', '.join(df.columns)}")
        text_column = st.selectbox("Select text column:", df.columns)

    # Spell Check Preview (show before running analysis if data is loaded and spell check is on)
    if df is not None and not has_results and spell_check_level != 'off':
        with st.expander("🔍 Preview Spell Check Corrections", expanded=False):
            st.caption("These corrections will be applied when you run analysis:")
            corrections = get_spelling_corrections_preview(df[text_column].dropna().tolist(), spell_check_level)
            if corrections:
                preview_df = pd.DataFrame(corrections)
                preview_df.columns = ['Original Word', 'Correction', 'Context (word in bold)']
                st.dataframe(preview_df, use_container_width=True, hide_index=True)
                st.warning(f"⚠️ {len(corrections)} word(s) will be corrected. Review the table above to verify corrections are appropriate.")
            else:
                st.success("✓ No spelling corrections detected at this level.")

    # Run Analysis
    if run_analysis_btn:
        with st.spinner("Running thematic analysis..."):
            # Initialize analyzer based on mode
            if analysis_mode == "Guided (Dictionary)":
                # Use edited theme dictionary if available
                theme_dict = st.session_state.get('custom_theme_dict', DEFAULT_THEME_DICTIONARY)
                analyzer = DictionaryAnalyzer(
                    theme_dictionary=theme_dict,
                    spell_check=spell_check_level
                )
            else:
                analyzer = ThematicAnalyzer(
                    n_topics=n_topics,
                    custom_stopwords=custom_stopwords,
                    spell_check=spell_check_level
                )

            # Run analysis with all options
            results = analyzer.analyze_dataframe(
                df,
                text_column=text_column,
                n_themes=n_themes,
                include_sentiment=include_sentiment,
                min_words=min_words
            )

            # Store in session state
            st.session_state['results'] = results
            st.session_state['analyzer'] = analyzer
            st.session_state['topic_words'] = analyzer.get_topic_words(n_words=10)
            st.session_state['n_themes'] = n_themes
            st.session_state['include_sentiment'] = include_sentiment
            st.session_state['min_words'] = min_words
            st.session_state['text_column'] = text_column

            # Store locked parameters
            st.session_state['locked_params'] = {
                'analysis_mode': analysis_mode,
                'text_column': text_column,
                'stratifier_column': stratifier_column,
                'stratifier_display_label': stratifier_display_label,
                'n_themes': n_themes,
                'spell_check': spell_check_level.capitalize() if spell_check_level != 'off' else 'Off',
                'min_words': min_words,
                'include_sentiment': include_sentiment,
                'n_topics': n_topics,
                'custom_stopwords': custom_stopwords
            }

        st.success("Analysis complete!")

    # Display results if available
    if 'results' in st.session_state:
        results = st.session_state['results']
        analyzer = st.session_state['analyzer']
        topic_words = st.session_state['topic_words']
        stored_n_themes = st.session_state.get('n_themes', 1)
        stored_include_sentiment = st.session_state.get('include_sentiment', True)
        stored_min_words = st.session_state.get('min_words', 5)
        stored_text_column = st.session_state.get('text_column', 'response')
        stored_locked_params = st.session_state.get('locked_params', {})
        stored_stratifier = stored_locked_params.get('stratifier_column', '')

        # Check if stratifier column exists in results
        has_stratifier = stored_stratifier and stored_stratifier in results.columns
        stratifier_label = stored_locked_params.get('stratifier_display_label', 'Group')

        # Show staleness warning if settings have changed
        if settings_modified:
            st.warning(
                "⚠️ **Settings have changed** - Results below reflect the previous configuration. "
                "Click **Update Results** in the sidebar to apply new settings."
            )

        # Metrics row
        col1, col2, col3, col4, col5 = st.columns(5)

        with col1:
            st.metric(
                "Total Responses",
                len(results),
                help="Number of responses analyzed."
            )

        with col2:
            # Count unique themes that were actually assigned (excluding special values)
            valid_themes = results[results['primary_theme_idx'] >= 0]['primary_theme'].nunique()
            st.metric(
                "Themes Found",
                valid_themes,
                help="Distinct themes with matching responses."
            )

        with col3:
            # Different metric based on analysis mode
            if isinstance(analyzer, DictionaryAnalyzer):
                valid_results = results[results['primary_fit_count'].notna()]
                if len(valid_results) > 0:
                    avg_matches = valid_results['primary_fit_count'].mean()
                    st.metric(
                        "Avg Keywords",
                        f"{avg_matches:.1f}",
                        help="Keywords per response. 3+ = strong match, <2 = weak match."
                    )
            else:
                valid_results = results[results['primary_fit'].notna()]
                if len(valid_results) > 0:
                    avg_confidence = valid_results['primary_fit'].mean()
                    st.metric(
                        "Avg Fit",
                        f"{avg_confidence:.0%}",
                        help="How clearly responses fit their assigned topic (0–100%). "
                             "**Above 40%** = strong fit; **20–40%** = moderate; "
                             "**below 20%** = response does not clearly belong to any single topic."
                    )

        with col4:
            if stored_include_sentiment and 'sentiment_score' in results.columns:
                avg_sentiment = results['sentiment_score'].mean()
                st.metric(
                    "Avg Sentiment",
                    f"{avg_sentiment:+.2f}",
                    help="Average sentiment score. Positive (>0.05), Neutral (-0.05 to 0.05), Negative (<-0.05)"
                )

        with col5:
            if has_stratifier:
                st.metric(
                    f"{stratifier_label}s" if not stratifier_label.endswith('s') else stratifier_label,
                    results[stored_stratifier].nunique(),
                    help=f"Number of distinct values in the '{stored_stratifier}' column."
                )

        # Show warning for below-minimum responses
        if stored_min_words > 0 and 'meets_length_min' in results.columns:
            below_min = (~results['meets_length_min']).sum()
            if below_min > 0:
                st.warning(f"⚠️ {below_min} response(s) below minimum length ({stored_min_words} words) - excluded from theme analysis")

        # Spell Check Results (collapsible)
        spell_level = stored_locked_params.get('spell_check', 'Off')
        if spell_level and spell_level.lower() != 'off':
            with st.expander("📝 Spell Check Corrections Applied", expanded=False):
                corrections = get_spelling_corrections_preview(
                    results[stored_text_column].dropna().tolist(),
                    spell_level.lower()
                )
                if corrections:
                    st.caption(f"The following corrections were applied during analysis (Spell Check: {spell_level}):")
                    preview_df = pd.DataFrame(corrections)
                    preview_df.columns = ['Original Word', 'Correction', 'Original Context']
                    st.dataframe(preview_df, use_container_width=True, hide_index=True)
                else:
                    st.success(f"✓ No spelling corrections were applied (Spell Check: {spell_level})")

        st.divider()

        # Two-column layout for visualizations
        col1, col2 = st.columns(2)

        with col1:
            st.subheader("Topic Distribution")
            topic_chart = create_topic_distribution_chart(results, analyzer)
            st.plotly_chart(topic_chart, use_container_width=True)

        with col2:
            st.subheader("Word Cloud")
            # Use processed text (after spell check) if available, otherwise use original
            wordcloud_text = results['_processed_text'] if '_processed_text' in results.columns else results[stored_text_column]
            fig = generate_wordcloud(wordcloud_text)
            if fig:
                st.pyplot(fig)
                plt.close()

        # Heatmap by stratifier (if applicable)
        if has_stratifier:
            st.subheader(f"Topic Distribution by {stratifier_label}")

            # Add filter option
            stratifier_values = ['All'] + sorted(results[stored_stratifier].dropna().unique().tolist())
            selected_stratifier_heatmap = st.selectbox(
                f"Filter by {stratifier_label}:",
                stratifier_values,
                key="heatmap_stratifier_filter"
            )

            if selected_stratifier_heatmap == 'All':
                heatmap_data = results
            else:
                heatmap_data = results[results[stored_stratifier] == selected_stratifier_heatmap]

            if selected_stratifier_heatmap == 'All':
                heatmap = create_stratifier_topic_heatmap(heatmap_data, stored_stratifier, stratifier_label)
                if heatmap:
                    st.plotly_chart(heatmap, use_container_width=True)
            else:
                # When filtered to single stratifier, show bar chart instead of heatmap
                topic_counts = heatmap_data['topic_label'].value_counts()
                fig = px.bar(
                    x=topic_counts.index,
                    y=topic_counts.values,
                    labels={'x': 'Topic', 'y': 'Count'},
                    title=f"Topic Distribution for {selected_stratifier_heatmap}"
                )
                fig.update_layout(height=300)
                st.plotly_chart(fig, use_container_width=True)

        # Sentiment distribution (if enabled)
        if stored_include_sentiment and 'sentiment_score' in results.columns:
            st.subheader("Sentiment Analysis")

            # Add stratifier filter if available
            if has_stratifier:
                stratifier_values_sentiment = ['All'] + sorted(results[stored_stratifier].dropna().unique().tolist())
                selected_stratifier_sentiment = st.selectbox(
                    f"Filter by {stratifier_label}:",
                    stratifier_values_sentiment,
                    key="sentiment_stratifier_filter"
                )
                if selected_stratifier_sentiment == 'All':
                    sentiment_data = results
                else:
                    sentiment_data = results[results[stored_stratifier] == selected_stratifier_sentiment]
            else:
                sentiment_data = results

            col1, col2 = st.columns([2, 1])

            with col1:
                sentiment_chart = create_sentiment_distribution_chart(sentiment_data)
                if sentiment_chart:
                    st.plotly_chart(sentiment_chart, use_container_width=True)

            with col2:
                # Sentiment breakdown
                pos_count = (sentiment_data['sentiment_label'] == 'Positive').sum()
                neu_count = (sentiment_data['sentiment_label'] == 'Neutral').sum()
                neg_count = (sentiment_data['sentiment_label'] == 'Negative').sum()
                total = len(sentiment_data)

                st.markdown("**Sentiment Breakdown**")
                if total > 0:
                    st.markdown(f"- 😊 Positive: {pos_count} ({pos_count/total*100:.1f}%)")
                    st.markdown(f"- 😐 Neutral: {neu_count} ({neu_count/total*100:.1f}%)")
                    st.markdown(f"- 😞 Negative: {neg_count} ({neg_count/total*100:.1f}%)")
                else:
                    st.markdown("No data for selected filter.")

        st.divider()

        # Topic Details
        st.subheader("Topic Details")

        if isinstance(analyzer, DictionaryAnalyzer):
            st.caption("Each theme shows its matched keywords. Weights are equal (1.00) for dictionary-based matching.")
        else:
            st.caption(
                "The number in parentheses is the **topic weight**: how strongly a word characterizes this topic. "
                "Higher = more distinctive. Compare weights within a topic to see which words define it most; "
                "the scale varies by dataset, so cross-topic comparisons are less meaningful."
            )

        for topic_idx in range(n_topics):
            with st.expander(f"📌 {analyzer.topic_labels[topic_idx]}", expanded=(topic_idx == 0)):
                # Top words
                words = topic_words[topic_idx]
                word_str = ", ".join([f"**{w}** ({score:.2f})" for w, score in words[:8]])
                st.markdown(f"**Top terms:** {word_str}")

                # Sample responses
                topic_responses = results[results['dominant_topic'] == topic_idx]
                st.markdown(f"**{len(topic_responses)} responses** assigned to this topic")

                if len(topic_responses) > 0:
                    st.markdown("**Sample responses:**")
                    for _, row in topic_responses.head(3).iterrows():
                        st.markdown(f"- _{row[stored_text_column]}_")

        st.divider()

        # Data Explorer
        st.subheader("Explore Responses")

        # Column guide
        with st.expander("Column definitions", expanded=False):
            col_defs = "| Column | Description |\n|--------|-------------|\n"
            col_defs += f"| **{stored_text_column}** | Original response text |\n"
            col_defs += "| **primary_theme** | Best-fit topic assigned to this response |\n"

            if isinstance(analyzer, DictionaryAnalyzer):
                col_defs += "| **primary_fit_count** | Number of dictionary keywords matched (higher = stronger match; 3+ is strong, <2 is weak) |\n"
                col_defs += "| **primary_fit_pct** | Percentage of the theme's keyword list that was matched |\n"
            else:
                col_defs += "| **primary_fit** | Probability the response belongs to its assigned topic (0–1). Above 0.40 = strong; 0.20–0.40 = moderate; below 0.20 = weak fit |\n"

            if stored_n_themes >= 2:
                col_defs += "| **secondary_theme** | Second-best topic match |\n"
            if stored_n_themes >= 3:
                col_defs += "| **tertiary_theme** | Third-best topic match |\n"

            if stored_include_sentiment and 'sentiment_score' in results.columns:
                col_defs += "| **sentiment_score** | VADER compound score (−1.0 to +1.0). Above +0.05 = positive, −0.05 to +0.05 = neutral, below −0.05 = negative |\n"
                col_defs += "| **sentiment_label** | Positive, Neutral, or Negative based on the score thresholds above |\n"

            col_defs += "| **word_count** | Number of words in the response |\n"

            if has_stratifier:
                col_defs += f"| **{stored_stratifier}** | {stratifier_label} grouping variable from the original data |\n"

            st.markdown(col_defs)

        # Filters
        # Determine coded vs uncoded status for each response
        uncoded_themes = {'Uncategorized', 'Below minimum length'}
        is_coded = ~results['primary_theme'].isin(uncoded_themes)
        coded_count = is_coded.sum()
        uncoded_count = (~is_coded).sum()

        filter_col1, filter_col2, filter_col3 = st.columns(3)

        with filter_col1:
            status_options = [
                f"All ({len(results)})",
                f"Coded ({coded_count})",
                f"Uncoded ({uncoded_count})"
            ]
            status_filter = st.radio(
                "Response status:",
                status_options,
                index=0,
                horizontal=True,
                help="**Coded**: assigned to a theme. **Uncoded**: no theme match (Uncategorized) or below minimum word count."
            )

        with filter_col2:
            topic_filter = st.multiselect(
                "Filter by topic:",
                options=list(analyzer.topic_labels.values()),
                default=[]
            )

        with filter_col3:
            if has_stratifier:
                stratifier_filter = st.multiselect(
                    f"Filter by {stratifier_label}:",
                    options=results[stored_stratifier].dropna().unique().tolist(),
                    default=[]
                )
            else:
                stratifier_filter = []

        # Apply filters
        filtered = results.copy()
        if status_filter.startswith("Coded"):
            filtered = filtered[~filtered['primary_theme'].isin(uncoded_themes)]
        elif status_filter.startswith("Uncoded"):
            filtered = filtered[filtered['primary_theme'].isin(uncoded_themes)]
        if topic_filter:
            filtered = filtered[filtered['primary_theme'].isin(topic_filter)]
        if stratifier_filter:
            filtered = filtered[filtered[stored_stratifier].isin(stratifier_filter)]

        # Build display columns based on what's available
        display_cols = [stored_text_column, 'primary_theme']

        # Add fit column based on analyzer type
        if isinstance(analyzer, DictionaryAnalyzer):
            if 'primary_fit_count' in results.columns:
                display_cols.append('primary_fit_count')
            if 'primary_fit_pct' in results.columns:
                display_cols.append('primary_fit_pct')
        else:
            if 'primary_fit' in results.columns:
                display_cols.append('primary_fit')

        # Add secondary/tertiary if applicable
        if stored_n_themes >= 2 and 'secondary_theme' in results.columns:
            display_cols.append('secondary_theme')
        if stored_n_themes >= 3 and 'tertiary_theme' in results.columns:
            display_cols.append('tertiary_theme')

        # Add sentiment if enabled
        if stored_include_sentiment and 'sentiment_score' in results.columns:
            display_cols.extend(['sentiment_score', 'sentiment_label'])

        # Add word count
        if 'word_count' in results.columns:
            display_cols.append('word_count')

        # Add stratifier/question if present
        if has_stratifier:
            display_cols.insert(0, stored_stratifier)
        if 'question' in results.columns:
            display_cols.insert(0, 'question')

        # Filter to only columns that exist
        display_cols = [c for c in display_cols if c in filtered.columns]

        st.dataframe(
            filtered[display_cols],
            use_container_width=True,
            height=400
        )

        # Uncoded Response Analysis
        uncoded_responses = results[results['primary_theme'].isin(uncoded_themes)]
        if len(uncoded_responses) > 0:
            st.divider()
            st.subheader(f"Uncoded Response Analysis ({len(uncoded_responses)} responses)")
            st.caption(
                "These responses were not assigned to any theme. "
                "Use the tools below to discover patterns and decide whether to add new themes or expand existing keyword lists."
            )

            # Feature 1: Frequent words in uncoded responses
            with st.expander("Frequent words in uncoded responses", expanded=True):
                from topic_modeling import ATLAS_STOPWORDS
                from collections import Counter

                # Get text from uncoded responses, basic preprocessing
                uncoded_texts = uncoded_responses[stored_text_column].dropna().astype(str)
                all_words = []
                for text in uncoded_texts:
                    words = re.sub(r'[^a-z\s]', ' ', text.lower()).split()
                    all_words.extend([w for w in words if len(w) > 2 and w not in ATLAS_STOPWORDS])

                if all_words:
                    word_freq = Counter(all_words).most_common(30)
                    freq_col1, freq_col2 = st.columns([2, 1])

                    with freq_col1:
                        freq_df = pd.DataFrame(word_freq, columns=['Word', 'Count'])
                        fig = go.Figure(data=[
                            go.Bar(
                                x=[w for w, _ in word_freq[:15]],
                                y=[c for _, c in word_freq[:15]],
                                marker_color='#f59e0b',
                                text=[c for _, c in word_freq[:15]],
                                textposition='auto'
                            )
                        ])
                        fig.update_layout(
                            title="Top 15 Words in Uncoded Responses",
                            xaxis_title="Word",
                            yaxis_title="Frequency",
                            height=350,
                            showlegend=False
                        )
                        st.plotly_chart(fig, use_container_width=True)

                    with freq_col2:
                        st.markdown("**All top 30 words:**")
                        st.dataframe(freq_df, use_container_width=True, height=350, hide_index=True)

                    # Suggest which existing themes these words might belong to
                    if isinstance(analyzer, DictionaryAnalyzer):
                        st.markdown("---")
                        st.markdown("**Suggestion:** Consider adding frequent words above to existing themes, or create a new theme in the sidebar.")
                else:
                    st.info("Uncoded responses contain no analyzable words after filtering.")

            # Feature 2: Run LDA on uncoded (if enough responses)
            min_for_lda = 20
            if len(uncoded_responses) >= min_for_lda:
                with st.expander("Discover themes with LDA", expanded=False):
                    st.markdown(
                        f"Run automatic topic modeling on the **{len(uncoded_responses)} uncoded responses** "
                        "to discover hidden patterns the dictionary may have missed."
                    )

                    lda_n_topics = st.slider(
                        "Number of topics to discover",
                        min_value=2,
                        max_value=min(6, len(uncoded_responses) // 5),
                        value=min(3, len(uncoded_responses) // 10),
                        key="uncoded_lda_topics"
                    )

                    if st.button("Run LDA on uncoded responses", key="run_uncoded_lda"):
                        with st.spinner("Running LDA on uncoded responses..."):
                            from topic_modeling import ThematicAnalyzer as LDA
                            uncoded_analyzer = LDA(
                                n_topics=lda_n_topics,
                                min_df=1,
                                spell_check=stored_locked_params.get('spell_check', 'Off').lower()
                            )
                            uncoded_texts_list = uncoded_responses[stored_text_column].tolist()
                            uncoded_analyzer.fit(uncoded_texts_list)
                            uncoded_topic_words = uncoded_analyzer.get_topic_words(n_words=8)

                            st.success("Done. Discovered topics:")
                            for t_idx in range(lda_n_topics):
                                words = uncoded_topic_words.get(t_idx, [])
                                word_str = ", ".join([f"**{w}** ({score:.2f})" for w, score in words])
                                st.markdown(f"**Discovered topic {t_idx + 1}:** {word_str}")

                            st.markdown("---")
                            st.markdown(
                                "**Next step:** If a discovered topic looks meaningful, add it as a new theme "
                                "in the sidebar (View/Edit Themes) with relevant keywords, then re-run analysis."
                            )
            else:
                if len(uncoded_responses) > 0:
                    st.caption(
                        f"LDA topic discovery requires at least {min_for_lda} uncoded responses "
                        f"(currently {len(uncoded_responses)}). Use the frequent words above to guide manual theme edits."
                    )

        st.divider()

        # Export Section
        st.subheader("Export Results")

        col1, col2 = st.columns(2)

        with col1:
            # Excel export with enhanced sheets
            buffer = BytesIO()
            with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
                # Sheet 1: Coded Responses (all data)
                results.to_excel(writer, sheet_name='Coded Responses', index=False)

                # Sheet 2: Theme Summary
                topic_summary = []
                for topic_idx in range(len(analyzer.topic_labels)):
                    if topic_idx not in analyzer.topic_labels:
                        continue
                    words = topic_words.get(topic_idx, [])

                    # Count by primary/secondary/tertiary
                    primary_count = (results['primary_theme_idx'] == topic_idx).sum()
                    secondary_count = (results['secondary_theme_idx'] == topic_idx).sum() if 'secondary_theme_idx' in results.columns and stored_n_themes >= 2 else 0
                    tertiary_count = (results['tertiary_theme_idx'] == topic_idx).sum() if 'tertiary_theme_idx' in results.columns and stored_n_themes >= 3 else 0

                    row_data = {
                        'Theme': analyzer.topic_labels[topic_idx],
                        'Primary Count': primary_count,
                        'Primary %': f"{primary_count/len(results)*100:.1f}%",
                    }
                    if stored_n_themes >= 2:
                        row_data['Secondary Count'] = secondary_count
                    if stored_n_themes >= 3:
                        row_data['Tertiary Count'] = tertiary_count
                    row_data['Top Words/Keywords'] = ", ".join([w for w, _ in words[:10]])

                    topic_summary.append(row_data)

                pd.DataFrame(topic_summary).to_excel(writer, sheet_name='Theme Summary', index=False)

                # Sheet 3: Sentiment Summary (if enabled)
                if stored_include_sentiment and 'sentiment_score' in results.columns:
                    sentiment_summary = pd.DataFrame({
                        'Metric': ['Mean Score', 'Median Score', 'Std Dev',
                                  'Positive Count', 'Neutral Count', 'Negative Count',
                                  'Positive %', 'Neutral %', 'Negative %'],
                        'Value': [
                            f"{results['sentiment_score'].mean():.3f}",
                            f"{results['sentiment_score'].median():.3f}",
                            f"{results['sentiment_score'].std():.3f}",
                            (results['sentiment_label'] == 'Positive').sum(),
                            (results['sentiment_label'] == 'Neutral').sum(),
                            (results['sentiment_label'] == 'Negative').sum(),
                            f"{(results['sentiment_label'] == 'Positive').sum()/len(results)*100:.1f}%",
                            f"{(results['sentiment_label'] == 'Neutral').sum()/len(results)*100:.1f}%",
                            f"{(results['sentiment_label'] == 'Negative').sum()/len(results)*100:.1f}%"
                        ]
                    })
                    sentiment_summary.to_excel(writer, sheet_name='Sentiment Summary', index=False)

                # Sheet 4: Data Quality
                if 'word_count' in results.columns:
                    quality_summary = pd.DataFrame({
                        'Metric': ['Total Responses', 'Valid Responses', 'Below Minimum Length',
                                  'Empty Responses', 'Average Word Count', 'Min Word Count', 'Max Word Count'],
                        'Value': [
                            len(results),
                            results['meets_length_min'].sum() if 'meets_length_min' in results.columns else len(results),
                            (~results['meets_length_min']).sum() if 'meets_length_min' in results.columns else 0,
                            (results['word_count'] == 0).sum(),
                            f"{results['word_count'].mean():.1f}",
                            results['word_count'].min(),
                            results['word_count'].max()
                        ]
                    })
                    quality_summary.to_excel(writer, sheet_name='Data Quality', index=False)

            st.download_button(
                label="📥 Download Excel",
                data=buffer.getvalue(),
                file_name="atlas_analysis_results.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )

        with col2:
            # CSV export
            csv = results.to_csv(index=False)
            st.download_button(
                label="📥 Download CSV",
                data=csv,
                file_name="atlas_analysis_results.csv",
                mime="text/csv"
            )

    else:
        st.info("👈 Click 'Run Analysis' in the sidebar to start thematic analysis")

        # Preview data
        if df is not None:
            st.subheader("Data Preview")
            st.dataframe(df.head(10), use_container_width=True)


if __name__ == "__main__":
    main()
