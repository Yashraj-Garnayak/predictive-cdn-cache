# Design: "How it works" animated explainer page

Date: 2026-11-22. Status: approved by owner. Not committed.

**Intent.** A beginner should understand the whole project by scrolling one page: the problem,
the data, the model, the four cache rules, the hourly loop, the metrics and the honest result.
It also shows off the project (portfolio and CV).

**Goals.**
- Add `web/how-it-works.html`, linked as "How it works" in the dashboard header.
- Tell the story as 10 scroll-driven steps. Each has a big visual, a 3–6 word heading and 1–2
  plain sentences.
- When a step scrolls into view, its boxes appear one by one, its arrows draw themselves and its
  numbers count up.
- Add a Next button and progress dots as an alternative to scrolling.
- Respect reduced motion: each step is then shown in its finished state.
- Work at laptop and phone widths.
- Load fast.

**Non-goals.** No new data or API calls. The numbers are fixed facts taken from the code and
`reports/baseline.csv`. No change to the dashboard beyond the header link.

**Anti-goals.** Numbers or rules that differ from the code. Heavy libraries.

**Constraints.**
- Same look as the dashboard: dark, frosted glass, the system font.
- Colours: Hybrid #0A84FF, LFU #BF5AF2, Predictive #FF9F0A, LRU #8E8E93, hit #30D158,
  miss #FF375F. These come from the tokens in `web/style.css`.
- No libraries (not even D3).

**Approach (picked: one sensible way).**
- Three plain files: `how-it-works.html`, `how-it-works.css` and `how-it-works.js`.
- Each visual is inline SVG or HTML.
- An IntersectionObserver adds an `in` class to a step when it enters the view. CSS transitions
  then do the work: delays for boxes appearing, `stroke-dashoffset` for arrows drawing.
- A small JS counter counts numbers up.
- Step 1 (request trip) and step 7 (loop) use CSS keyframes.
- Rejected: an animation library (heavy, not needed); canvas (not accessible, harder to theme).

**Facts the page must match (from the code).**
1. Cache of 200 objects; a hit is served from the nearby cache, a miss goes to the origin.
2. Meta CDN traces → `scripts/prepare_cachemon.py` (the 20,000 most-requested objects per cluster)
   → about 57M request rows → hourly counts, 2.9M rows (`requests_hourly`) → PostgreSQL in Azure
   (or the CSV).
3. Hours are split in half. The first half is warm-up: the model trains and the caches fill,
   with scores reset at the end. The second half is test: predict, then score. Features use only
   past hours.
4. The clues are lag 1, 2, 3, 6 and 24 h, growth (lag 1 − lag 2), the 6 h average and the hour of
   day. The answer is next hour's requests.
5. The model is `HistGradientBoostingRegressor` with 200 trees: each tree fixes part of the
   remaining error, and the guess is the sum.
6. The four rules:
   - LRU throws out the least recently used item.
   - LFU throws out the least frequently used item, but refuses a newcomer whose count is lower.
   - Predictive is LRU, pre-warmed each hour with the model's top 100 picks (50% of capacity).
   - Hybrid is LRU on 180 slots plus 20 reserved slots (10%) holding model picks LRU doesn't have.
7. The hourly loop: predict → rank → pre-load (Predictive and Hybrid) → replay this hour's real
   requests in shuffled order → count hits and misses → next hour.
8. Metrics: hit rate = hits / requests; precision@10 = overlap of the predicted and real top 10,
   divided by 10; MAE = average |predicted − actual|.
9. Results at cache 200 (held-out hours, `reports/baseline.csv`), by region (eag / nha / prn):

   | Policy | eag | nha | prn |
   |---|---|---|---|
   | LRU | 80.97 | 50.53 | 67.42 |
   | LFU | 69.13 | 21.42 | 56.54 |
   | Predictive | 80.98 | 50.55 | 67.43 |
   | Hybrid | 81.18 | 50.93 | 67.80 |

   Lesson: recent requests matter most. Prediction adds only a little on top of recency.
10. An overview of all steps; each part is clickable and jumps back to its step.

**Left to the builder.** Exact animation timings, illustrations and copy wording within these
facts.
