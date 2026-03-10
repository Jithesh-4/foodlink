"""
ai_utils.py — AI helper functions for FoodLink
Uses Ollama (gemma:2b) locally for:
  1. interpret_voice_query()  → converts natural language → search keywords
  2. translate_text()         → translates text to a target language
"""

import ollama


def interpret_voice_query(query: str) -> str:
    """
    Convert a natural language voice sentence into simple food search keywords.
    
    Examples:
      "I want free food near me"     → "free meal"
      "cheap food nearby"            → "discount"
      "where can I get biryani"      → "biryani"
      "List me the nearby food sources" → ""   (show all)
      "government ration shop"       → "ration"
    
    Returns a short keyword string (2-4 words max) or "" to show all results.
    """
    prompt = f"""You are a food search assistant for a food donation app in India.

Convert the following voice/text query into simple search keywords that match food listing titles.

Rules:
- If the query is a general request like "show all", "list food", "nearby food", "all food sources" → return exactly: SHOW_ALL
- If the query mentions free food → return: free meal
- If the query mentions cheap, discount, affordable food → return: discount  
- If the query mentions ration, government food → return: ration
- If the query mentions a specific food name (biryani, rice, dal, roti, bread, curry) → return that food name
- For any other specific query → return 2-3 keywords maximum
- Return ONLY the keywords, nothing else. No explanation, no punctuation.

Query: {query}

Keywords:"""

    try:
        response = ollama.chat(
            model='gemma:2b',
            messages=[{"role": "user", "content": prompt}],
            options={"temperature": 0.1}   # low temp = consistent output
        )
        result = response['message']['content'].strip()
        
        # Clean up the result
        result = result.replace('"', '').replace("'", '').strip()
        
        # If model says show all → return empty string (shows all cards)
        if result.upper() == 'SHOW_ALL' or len(result) < 2:
            return ''
        
        return result.lower()[:50]   # cap at 50 chars

    except Exception as e:
        print(f"[ai_utils] interpret_voice_query error: {e}")
        # Fallback: basic keyword extraction without AI
        return _simple_keyword_extract(query)


def translate_text(text: str, lang: str) -> str:
    """
    Translate text to the given language code.
    lang: 'ta' = Tamil, 'hi' = Hindi, 'te' = Telugu, 'kn' = Kannada, 'en' = English
    
    Used by /ai/translate route for dynamic content translation.
    """
    lang_names = {
        'ta': 'Tamil',
        'hi': 'Hindi', 
        'te': 'Telugu',
        'kn': 'Kannada',
        'en': 'English'
    }
    target = lang_names.get(lang, 'English')
    
    if lang == 'en':
        return text   # no translation needed
    
    prompt = f"""Translate the following text to {target}. 
Return ONLY the translated text, nothing else.

Text: {text}

Translation:"""

    try:
        response = ollama.chat(
            model='gemma:2b',
            messages=[{"role": "user", "content": prompt}],
            options={"temperature": 0.1}
        )
        return response['message']['content'].strip()
    except Exception as e:
        print(f"[ai_utils] translate_text error: {e}")
        return text   # return original if translation fails


def _simple_keyword_extract(query: str) -> str:
    """
    Fallback keyword extractor — no AI needed.
    Used when Ollama is not running or fails.
    """
    query_lower = query.lower()
    
    # General / show-all phrases → return empty (show all)
    show_all_phrases = [
        'list', 'show', 'all', 'nearby food', 'food sources', 
        'available food', 'what food', 'any food', 'find food'
    ]
    for phrase in show_all_phrases:
        if phrase in query_lower:
            return ''
    
    # Specific food type keywords
    keyword_map = {
        'free': 'free meal',
        'no cost': 'free meal',
        'cost free': 'free meal',
        'இலவச': 'free meal',        # Tamil: free
        'मुफ्त': 'free meal',         # Hindi: free
        'ఉచిత': 'free meal',         # Telugu: free
        'ಉಚಿತ': 'free meal',         # Kannada: free
        'cheap': 'discount',
        'discount': 'discount',
        'affordable': 'discount',
        'ration': 'ration',
        'government': 'ration',
        'ரேஷன்': 'ration',           # Tamil: ration
        'राशन': 'ration',            # Hindi: ration
    }
    for kw, result in keyword_map.items():
        if kw in query_lower:
            return result
    
    # Food names — extract and return
    food_names = [
        'biryani', 'rice', 'dal', 'daal', 'roti', 'chapati', 
        'bread', 'curry', 'sambar', 'idli', 'dosa', 'soup',
        'chicken', 'veg', 'vegetarian', 'lunch', 'dinner', 'breakfast'
    ]
    for food in food_names:
        if food in query_lower:
            return food
    
    # Last resort: return the last 3 words as keywords
    words = query_lower.split()
    return ' '.join(words[-3:]) if len(words) >= 3 else query_lower