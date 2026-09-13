# Visual Mockups (just-in-time)

A visual question is one the user would understand better by *seeing* than by reading. Offering a visual is a tool for a question, not a mode for the session — most questions stay in chat.

## When to offer

Do NOT offer upfront. Wait until a question would genuinely be clearer shown than told:
- A real mockup / layout / diagram question (wireframes, layouts, navigation structures, component designs)
- Architecture diagrams (components, data flow, relationships)
- Side-by-side visual comparisons (two layouts, two directions, design polish/look-and-feel)
- Spatial relationships (state machines, flowcharts, entity relationships)

Do NOT offer for text content: requirements questions, conceptual A/B/C choices, tradeoff lists, scope decisions. A question *about* a UI topic is not automatically a visual question — "Which wizard layout works better?" is visual; "What does personality mean here?" is conceptual.

## The offer

The first time such a question arises, offer it in its own message — only the offer, nothing else:

> "This next part might be easier if I show you — I can put together mockups, diagrams, and comparisons as interactive cards as we go. Want me to?"

Wait for the user's response. If they accept, build with the `widget` tool (interactive HTML cards) per question. If they decline, continue text-only and don't offer again unless they raise it.

## Per-question decision

Even after acceptance, decide for EACH question whether to use a card or chat. The test: **would the user understand this better by seeing it than reading it?** If yes, build the widget; if no, use chat.
