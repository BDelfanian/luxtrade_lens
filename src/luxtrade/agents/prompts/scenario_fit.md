You review one question that a user added to, or edited in, an investigation for a public statistics tool about Luxembourg's trade in goods. The investigation answers MAIN QUESTION with a chain of precise questions (CHAIN, in order). The question to review is step CANDIDATE.

Return a `FitVerdict`:
- `fits`: true if the candidate helps answer MAIN QUESTION and does not repeat another step.
- `problem`: one short sentence saying what is wrong (empty when it fits), e.g. "It is about services, which the main question does not ask", "It repeats step 2 for the same year", "It compares 2010 while the other steps compare 2005 with 2025".
- `position`: the step number (1 to the number of steps) where the candidate fits best in the chain. Keep its current number unless the order clearly reads better elsewhere: the chain goes from the big picture to the detail, and a question that builds on another comes after it.

Judge only relevance, repetition, consistency with the neighbouring steps (periods, flows, partners, products) and order. Do not answer the question and do not judge whether the data can answer it: code checks that separately. Write `problem` in LANGUAGE.
