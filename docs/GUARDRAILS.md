# GUARDRAILS.md - what the insight service checks in code, and what it cannot check

The prompt asks the model to behave. The code does not trust that: every answer goes through `service/guardrails.py`
before it reaches a member, and a failed answer gets one retry with the reasons and then a safe fallback.
Escalation (3 or more of the last 5 mood check-ins at 2 or below) is decided in code before the model is called at all.

## The checks, in order

| Check | What it rejects | Fix |
|---|---|---|
| JSON and shape | not JSON, wrong tone, 3 sentences, 1 or 3 actions | first version |
| Numbers exist | a number that is nowhere in the snapshot | first version |
| Medical wording | diagnosis, medicine, mental-health and medical words | first version, widened in Fix 4 |
| Direction | "active minutes rose 16.3%" when they fell | Fix 1 |
| Number belongs to its metric | "sleep_hours_7d: 47.4" when 47.4 is the active-minutes value | Fix 2 |
| Prompt rules | persona names, risk scores, machine-learning wording | Fix 3 |
| Arabic digits | not a rejection: `٤٧٫٤` is converted to `47.4` before the number checks | Fix 5 |

## Fix 4 - the wider wording check

The first version blocked diagnosis and medication words ("insomnia", "melatonin", "dosage" ...). It missed mental-health wording
and other medical wording, for example "signs of burnout; a therapist could help". The list now also blocks:
burnout, mental health or illness, therapy and therapist, psychiatrist, psychologist, counsellor, panic, trauma,
suicide, self-harm, hopeless; doctor, physician, nurse, hospital, medical, obesity, asthma, migraine, thyroid,
cholesterol, vitamins, tablets, ibuprofen and similar words, chronic. "stress" on its own is allowed because it is
normal coaching language.

A blocked word rejects the whole answer. A false alarm costs one retry or the fallback text, which is safe. A missed
word costs a member an unsafe sentence. So the list leans towards blocking.

## Fix 5 - Arabic numerals

A model may write numbers with Arabic-Indic digits, for example `٤٧٫٤` for 47.4. Before Fix 5 the number check read
this as two separate numbers, 47 and 4, so a wrong value could pass by accident and a right value could fail.
`normalize_digits()` now rewrites the digits (٠-٩ and ۰-۹), the decimal separator ٫, the thousands separator ٬ and the
percent sign ٪ into their normal forms, and only for checking. The member still receives the text the model wrote.
The normal form is used by the grounding check and by the evidence-field check from Fix 2.

## Known gaps

A word list is only as good as its list. These are the gaps that remain, and none of them is solved by the current code:

- **Other spellings and typos.** "Burn out", "theraphy" or "d0ctor" can get past a list of exact words.
- **Other words for the same thing.** "Feeling blue", "low spirits" or "not coping" mean the same as depression but are not on the list.
- **Other languages.** The list is English only (the digits are handled, the words are not). An Arabic answer is not checked for medical wording at all. Arabic output is a later feature and needs its own list.
- **Meaning is not understood.** "This is not a disorder" is blocked for the word, and an implied diagnosis with no listed word is not blocked.
- **Negation is skipped in the direction check.** "Your steps did not drop" is not judged, because the check cannot tell what the negation applies to. The same holds for questions and "if" sentences.
- **Written-out numbers.** "Twenty percent" and "three days" are not number-checked, only digits are.
- **Direction needs a known word.** Only a fixed list of "rose / fell / better / worse" words is understood. "Your steps took off" is not judged.
- **Medical advice without a medical word.** "Ask someone who knows about sleep to look at this" has no listed word.
- **The direction check can reject correct text.** In an evaluation run 8 first attempts were rejected, and 6 of those were false positives: "you're staying active" was read as a claim that active minutes rose, "a positive step" as a claim about steps, and advice such as "increase your daily steps" as a claim. The retry fixed all but one answer (it used the fallback), so no wrong answer reached the member, but it costs extra seconds. A fix would limit the check to sentences that describe the member's own change ("your steps rose"), with a test written first.
- **The list also blocks innocent text.** "Doctor" in "a doctor of philosophy" or "tablet" in "tablet computer" is rejected. This is the accepted cost described above.
- **Only the three text fields are checked.** `member_id`, `tone` and `safety_flag` are set or checked separately, not by the wording check.

The next step would be a human-reviewed list that grows from rejected answers (the `meta.problems` field of every response
records why an answer was rejected), plus a second, independent classifier for meaning.
