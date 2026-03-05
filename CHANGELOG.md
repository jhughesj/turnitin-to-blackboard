# Changelog

## [2.0.0] - 2026-03-06
**v2.0 -- Smart extraction & robustness fixes**

**Smart sentence extraction**
Replaced sequential sentence selection with scored extraction — sentences containing specific,
checkable requirements (referencing styles, named requirements, institutional specifics) are now prioritised over generic quality prose regardless of their position in the descriptor
Added _HIGH_VALUE_SIGNALS list (+10 each): Harvard/APA/MLA/Chicago/Vancouver, bibliography, peer-reviewed, primary source, plagiarism, similarity score, originality, AI-generated content, word count/limit, template, supervisor, 
Westminster, UN SDGs, GDPR, data protection, knowledge gap, statistical, lay/expert audience, and more

Added _MEDIUM_VALUE_SIGNALS list (+8 each): images, visuals, diagrams, figures, charts, screenshots
Added _GENERIC_OPENERS penalty list (-3): suppresses generic quality sentences that add no information value
Targeted budget boost for low-weighted criteria (e.g. Research Q, Presentation) whose critical sentence would otherwise be cut by proportional allocation alone

Bug fixes:
Ascending scale fix: rubrics whose grade levels sort 0%→100% (rather than 100%→0%) were producing swapped Distinction/Fail descriptors — now identifies top/bottom grade by actual numeric value, not position order
Level range display: now always shows highest grade first (e.g. "100% to 0%", "85-100 to 0-29")

Criterion description truncation: 
very long descriptions (e.g. full coursework task instructions used as criterion text) are now capped at 150 chars to prevent base prompt bloat

Over-limit rubrics:
Rubrics that exceed the character limit even without descriptors (e.g. 20 criteria with full task instructions) now return a clear warning file explaining why conversion failed and what to do instead, rather than a garbled, truncated prompt
