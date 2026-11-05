# Requirements status

This document gives one evidence line for each acceptance criterion in [`docs/requirements.md`](requirements.md), so you can see which criteria a passing test proves, which ones a live run must still prove, and which ones the code does not meet yet. It describes commit `d931761` on `feat/complete-requirements`. Each `Driven` row names the commit its drive ran on; a row driven on an earlier commit is still the latest live evidence for it. Every test cited below passes there. To rerun all of them, run `cd backend && uv run pytest -q $(grep -o 'tests/test_[a-z0-9_]*\.py::[a-z0-9_]*' ../docs/requirements-status.md | sort -u)` from the repository root.

The technical strategy rows (US-001, the Buzz strategy rows, US-303 and US-304) were updated on 2026-11-03 for the formula design in [`docs/technical-strategy-formulas.md`](technical-strategy-formulas.md); their evidence is the tests of that change.

Each row has one status:

- `Done` means that a test asserts what the criterion asks for, and the test passes. The Evidence cell gives its pytest node ID, relative to `backend/`.
- `Needs drive` means that only a live CLI or Web API run can prove the criterion, for example text the menu prints or a real AI answer. The Evidence cell names the feature file and the sub-feature ID in the verification map, `.claude/skills/verify-stock-agent/features/` in the main checkout. Git does not track that folder.
- `Partial` means that the criterion is not fully proven. The Evidence cell starts with `Untested.` when the code meets the criterion but no test, or no test against the real service, asserts it. It starts with `Missing.` when the code does not meet part of the criterion.
- `Not done` means that the code does not do what the criterion asks.
- `Driven` means that a live CLI or Web API drive showed what the criterion asks for. The Evidence cell names the sub-feature and the drive's transcript, under `~/.cache/stock-agent-verify-final/evidence/` on the integrator's machine.
- `Superseded` means that the owner ruled that another criterion replaces this one. The Evidence cell gives the ruling and the test of what the code does instead.

Source paths are relative to `backend/src/`, except paths that start with `config/`, `docs/` or `README.md`, which are relative to the repository root. Criterion numbers follow the order of the bullets in `docs/requirements.md`. A nested bullet list is part of its parent criterion. The last section covers the technical debt and enabler list at the end of `docs/requirements.md`.

## US-001 Calculate the technical score

| # | Criterion | Status | Evidence |
| --- | --- | --- | --- |
| 1 | Every stock that completes technical filtering has a `technical_score`. | Done | `tests/test_workflow_orchestration.py::test_specific_stock_analysis_returns_manual_watchlist_candidates_without_orders` gives the passing and the failing stock a composite score, which `CompositeScorer` computes only from a technical score. `tests/test_web_api.py::test_specific_stock_analysis_reports_each_requested_stock` reads the score 90. |
| 2 | The score is between 0 and 100. | Done | `tests/test_technical_formula.py::test_the_score_stays_between_0_and_100` |
| 3 | Hard failures, soft failures and indicator bonuses change the score. | Done | `tests/test_technical_formula.py::test_failures_and_bonuses_of_several_rules_add_up`, `tests/test_technical_formula.py::test_a_rules_effect_applies_once_however_many_conditions_it_holds` |

The questions below the US-001 criteria, whether the domain models are split too finely and where the scoring settings belong, are answered in [`docs/technical-domain-review.md`](technical-domain-review.md).

## US-002 Save the technical watchlist

| # | Criterion | Status | Evidence |
| --- | --- | --- | --- |
| 1 | Full Cycle marks its technical survivors `WatchlistType.TECHNICAL`. | Done | `tests/test_workflow_orchestration.py::test_full_cycle_saves_only_survivors_as_technical_and_never_orders` |
| 2 | The stocks join the runtime watchlist. | Done | `tests/test_workflow_orchestration.py::test_full_cycle_saves_only_survivors_as_technical_and_never_orders`. Signals are generated from `status.watchlist`, and the survivor gets its BUY signal. |
| 3 | The watchlist is persisted through the repository. | Done | `tests/test_watchlist_rule.py::test_a_stock_holds_every_type_it_was_added_under_merged_by_stock_id` writes and reads the real `WatchlistRepository` on SQLite. |
| 4 | The repository never guesses `TECHNICAL` when the source is missing. | Done | `tests/test_watchlist_rule.py::test_an_entry_without_a_type_is_refused_before_the_repository_can_save_it_as_technical`, `tests/test_watchlist_rule.py::test_a_stored_row_without_a_type_fails_to_load_instead_of_reading_as_technical`. The source field is now `watchlist_type`, and the real SQLite `WatchlistRepository` refuses to save or load a row without one. |
| 5 | Every watchlist entry has an explicit `candidate_source`. | Done | `tests/test_watchlist_rule.py::test_a_watchlist_entry_cannot_be_made_without_its_type`. `WatchlistEntry.watchlist_type` replaced `candidate_source`. |

## US-003 Add stocks to the manual watchlist

| # | Criterion | Status | Evidence |
| --- | --- | --- | --- |
| 1 | The CLI asks the user after it shows the analysis report. | Driven | `analyse-specific-stocks.md: specific-manual-watchlist`, driven 2026-10-31 on 59ba50d (`~/.cache/stock-agent-verify-final/evidence/fd-specific/manual-watchlist-buy/transcript.txt`): `Stock Reports` prints at line 73 and `Add these stocks to the manual watchlist?` at line 83. |
| 2 | Only `survivors` can be added. | Superseded | The owner ruled on 2026-10-31 that US-005 #9 replaces this rule, and `docs/requirements.md` notes it under US-003. The CLI offers every reported stock, and `tests/test_workflow_orchestration.py::test_specific_stock_watchlist_prompt_writes_only_manual_rows` adds the technically failed 2317 as `MANUAL`. |
| 3 | Declining leaves the watchlist unchanged. | Done | `tests/test_workflow_orchestration.py::test_specific_stock_watchlist_prompt_writes_only_manual_rows`, the `declined` case. |
| 4 | Accepting marks the stocks `WatchlistType.MANUAL`. | Done | `tests/test_workflow_orchestration.py::test_specific_stock_watchlist_prompt_writes_only_manual_rows`, the `confirmed` case. |
| 5 | An existing entry merges according to `WatchlistRule`. | Done | `tests/test_watchlist_rule.py::test_a_stock_holds_every_type_it_was_added_under_merged_by_stock_id`, `tests/test_watchlist_rule.py::test_adding_a_manual_stock_twice_reports_it_as_already_present` |
| 6 | `MANUAL` outranks `TECHNICAL` and `BUZZ`. | Done | `tests/test_watchlist_rule.py::test_manual_entries_never_expire_and_outlive_automatic_ones` |
| 7 | The CLI shows the result to the user. | Done | `tests/test_watchlist_rule.py::test_the_cli_reports_newly_added_and_already_present_manual_stocks` |

## US-004 Trade manually watched stocks

| # | Criterion | Status | Evidence |
| --- | --- | --- | --- |
| 1 | The trading workflow loads active `MANUAL` stocks. | Done | `tests/test_stock_candidates.py::test_intraday_candidates_are_held_stocks_plus_the_active_watchlist` loads the `MANUAL` 2603. |
| 2 | Manual stocks merge with the other active watchlist stocks by `stock_id`. | Done | `tests/test_stock_candidates.py::test_intraday_candidates_are_held_stocks_plus_the_active_watchlist` gives the held, `TECHNICAL` and `BUZZ` 2330 one stock. |
| 3 | Duplicate sources never make the workflow analyse a stock twice. | Done | `tests/test_workflow_orchestration.py::test_intraday_loads_held_positions_and_active_watchlist` analyses the held and watched 2330 once. |
| 4 | The workflow refreshes market data before it decides. | Done | `tests/test_workflow_orchestration.py::test_intraday_places_no_order_for_a_stale_quote`, `tests/test_market_data_freshness.py::test_a_fresh_quote_is_not_asked_for_again_and_clears_the_stale_mark` |
| 5 | The workflow runs the normal technical analysis, AI analysis and composite score. | Done | `tests/test_workflow_orchestration.py::test_intraday_loads_held_positions_and_active_watchlist` passes both stocks through the technical filter to the AI. `tests/test_workflow_orchestration.py::test_one_runs_buys_risk_a_share_of_the_equity_best_score_first_until_the_cash_runs_out` orders the BUYs by composite score. |
| 6 | `composite_score` is the computed score, not a default. | Done | `tests/test_workflow_orchestration.py::test_one_runs_buys_risk_a_share_of_the_equity_best_score_first_until_the_cash_runs_out` gets a different BUY order from each AI score. `tests/test_ai_report_parser.py::test_a_parsed_ai_score_feeds_the_composite_score` turns 80 and 60 into 70. |
| 7 | The normal `DecisionRule` decides BUY, HOLD or SELL. | Done | `tests/test_workflow_orchestration.py::test_intraday_buys_holds_and_sells_manually_watched_stocks_on_their_composite_score` runs menu 3 on three `MANUAL` stocks, which buy at composite 90, hold at 65 and sell the held position at the sell threshold of 50. |
| 8 | A BUY for a manually watched stock carries the decision source, not the watchlist source. | Done | `tests/test_workflow_orchestration.py::test_an_automatic_buy_of_a_manually_watched_stock_is_a_combined_decision_never_a_manual_one` |
| 9 | A `MANUAL` watchlist stock never creates a `SignalSource.MANUAL` signal by itself. | Done | `tests/test_workflow_orchestration.py::test_an_automatic_buy_of_a_manually_watched_stock_is_a_combined_decision_never_a_manual_one`, the `intraday` case. |
| 10 | Normal position sizing applies. | Done | `tests/test_workflow_orchestration.py::test_one_runs_buys_risk_a_share_of_the_equity_best_score_first_until_the_cash_runs_out` |
| 11 | Normal risk checks apply. | Done | `tests/test_web_api.py::test_no_api_request_reaches_the_broker` runs menu 3, which sells the held 2317 at its stop-loss. |
| 12 | Normal order validation applies. | Done | `tests/test_workflow_orchestration.py::test_order_execution_skips_closed_market_orders`, `tests/test_workflow_orchestration.py::test_intraday_places_no_order_for_a_stale_quote` |
| 13 | `OrderExecution` stays responsible for executable orders. | Done | `tests/test_workflow_orchestration.py::test_order_execution_skips_closed_market_orders`, `tests/test_trading_audit.py::test_the_order_is_recorded_pending_before_the_broker_sees_it` |
| 14 | Adding a stock to the manual watchlist never creates an order by itself. | Done | `tests/test_workflow_orchestration.py::test_specific_stock_watchlist_prompt_writes_only_manual_rows` |

## US-004-1 Manual BUY override

| # | Criterion | Status | Evidence |
| --- | --- | --- | --- |
| 1 | The CLI shows the specific-stock report before it offers Manual BUY. | Driven | `analyse-specific-stocks.md: specific-manual-buy`, driven 2026-10-31 on 59ba50d (`~/.cache/stock-agent-verify-final/evidence/fd-specific/manual-watchlist-buy/transcript.txt`): `Stock Reports` prints at line 73 and `BUY 2330 now using manual override?` at line 87. |
| 2 | The report carries the computed `composite_score`. | Done | `tests/test_web_api.py::test_specific_stock_analysis_reports_each_requested_stock` turns the technical score 90 and the AI score 70 into 80. |
| 3 | The user must confirm Manual BUY explicitly. | Done | `tests/test_workflow_orchestration.py::test_confirmed_manual_buy_sends_one_manual_signal_to_the_broker` buys only the confirmed 2317. |
| 4 | Declining creates no signal and no order. | Done | `tests/test_workflow_orchestration.py::test_specific_stock_watchlist_prompt_writes_only_manual_rows` declines every BUY prompt and finds no signal and no order. |
| 5 | The Manual BUY confirmation is separate from the manual watchlist confirmation. | Done | `tests/test_workflow_orchestration.py::test_confirmed_manual_buy_sends_one_manual_signal_to_the_broker` buys without a watchlist row, and `tests/test_workflow_orchestration.py::test_specific_stock_watchlist_prompt_writes_only_manual_rows` adds rows without a BUY. |
| 6 | A confirmed Manual BUY creates a `TradeSignal` with BUY and `SignalSource.MANUAL`. | Done | `tests/test_workflow_orchestration.py::test_confirmed_manual_buy_sends_one_manual_signal_to_the_broker`. The action enum is `TradeAction`, not `SignalAction`. |
| 7 | The latest account is loaded before the quantity is calculated. | Done | `tests/test_trading_audit.py::test_a_manual_buy_that_cannot_become_an_order_says_why` sizes no share from a 50 TWD account. |
| 8 | The existing sizing rules calculate a valid quantity. | Done | `tests/test_trading_audit.py::test_an_order_row_traces_back_to_its_price_reports_signal_run_and_result` buys 2,000 shares, 2% of 1,000,000 over a 10 TWD stop per share. |
| 9 | The quantity is greater than zero. | Done | `tests/test_workflow_orchestration.py::test_confirmed_manual_buy_sends_one_manual_signal_to_the_broker`, `tests/test_trading_audit.py::test_a_manual_buy_that_cannot_become_an_order_says_why` |
| 10 | Manual BUY does not ask `EntryRule` whether a BUY is allowed. | Done | `tests/test_workflow_orchestration.py::test_a_confirmed_manual_buy_is_sent_even_below_the_automatic_buy_threshold` buys a stock at composite 42, below `min_combined_score_buy`. |
| 11 | The existing signal persistence saves the signal. | Done | `tests/test_trading_audit.py::test_an_order_row_traces_back_to_its_price_reports_signal_run_and_result` reads the `trade_signals` row. |
| 12 | The signal goes through the existing `OrderExecution`. | Done | `tests/test_trading_audit.py::test_the_order_is_recorded_pending_before_the_broker_sees_it` |
| 13 | Manual BUY does not bypass order validation. | Done | `tests/test_trading_audit.py::test_a_refused_manual_buy_is_a_recorded_rejected_order_with_its_reason` |
| 14 | Execution checks an open market, a valid price, a quantity above zero, enough cash and the broker's constraints. | Done | `tests/test_trading_audit.py::test_only_continuous_trading_takes_the_apps_ioc_orders`, `tests/test_trading_audit.py::test_a_refused_manual_buy_is_a_recorded_rejected_order_with_its_reason` (closed market, stale price), `tests/test_trading_audit.py::test_a_manual_buy_that_cannot_become_an_order_says_why` (zero shares), `tests/test_mock_execution_provider.py::test_business_refusals_are_rejected_before_acceptance` (cash), `tests/test_mock_execution_provider.py::test_rod_is_rejected_because_nothing_could_fill_its_working_remainder` (broker constraint) |
| 15 | A rejected order reaches the user as a rejection, not as a silent success. | Done | `tests/test_cli_trading.py::test_a_refused_manual_buy_shows_its_status_and_reason` |
| 16 | Full Cycle never creates a `SignalSource.MANUAL` signal by itself. | Done | `tests/test_workflow_orchestration.py::test_an_automatic_buy_of_a_manually_watched_stock_is_a_combined_decision_never_a_manual_one`, the `full-cycle` case. |
| 17 | Manual BUY comes only from an explicit user action. | Done | `tests/test_workflow_orchestration.py::test_specific_stock_watchlist_prompt_writes_only_manual_rows` finds no signal without a BUY confirmation. `tests/test_web_api.py::test_the_api_writes_only_runs_watchlist_and_settings_and_says_it_never_orders` shows that the API has no Manual BUY. |

## US-005 Complete specific-stock analysis with human override

| # | Criterion | Status | Evidence |
| --- | --- | --- | --- |
| 1 | `manual_stocks` holds every requested stock that loaded. | Done | `tests/test_workflow_orchestration.py::test_specific_stock_analysis_returns_manual_watchlist_candidates_without_orders`, `tests/test_stock_candidates.py::test_lookup_loads_each_requested_stock_once_and_reports_unknown_ids` |
| 2 | `survivors` holds only the stocks that passed the active strategy. | Done | `tests/test_workflow_orchestration.py::test_specific_stock_analysis_returns_manual_watchlist_candidates_without_orders` |
| 3 | Every manual stock gets a `TechnicalReport`. | Done | `tests/test_workflow_orchestration.py::test_specific_stock_analysis_returns_manual_watchlist_candidates_without_orders` finds hard failures and a composite score on the failing stock. |
| 4 | A technical failure stays visible in `hard_failures`. | Done | `tests/test_workflow_orchestration.py::test_specific_stock_analysis_returns_manual_watchlist_candidates_without_orders` |
| 5 | `NewsFeed` processes every manual stock. | Done | `tests/test_workflow_orchestration.py::test_specific_stock_analysis_returns_manual_watchlist_candidates_without_orders` |
| 6 | `AiAnalyser` processes every manual stock. | Done | `tests/test_workflow_orchestration.py::test_specific_stock_analysis_returns_manual_watchlist_candidates_without_orders` |
| 7 | `AiAnalyser` gives every fully analysed manual stock its composite score. | Done | `tests/test_workflow_orchestration.py::test_specific_stock_analysis_returns_manual_watchlist_candidates_without_orders` |
| 8 | A technically failed manual stock can still get an AI score and a composite score. | Done | `tests/test_workflow_orchestration.py::test_specific_stock_analysis_returns_manual_watchlist_candidates_without_orders` |
| 9 | A technically failed manual stock can still be added as `WatchlistType.MANUAL`. | Done | `tests/test_workflow_orchestration.py::test_specific_stock_watchlist_prompt_writes_only_manual_rows` |
| 10 | Adding a failed stock to the `MANUAL` watchlist does not add it to `survivors`. | Done | `tests/test_workflow_orchestration.py::test_specific_stock_watchlist_prompt_writes_only_manual_rows` |
| 11 | Adding a stock to the `MANUAL` watchlist creates no signal and no order. | Done | `tests/test_workflow_orchestration.py::test_specific_stock_watchlist_prompt_writes_only_manual_rows` |
| 12 | Manual BUY stays a separate explicit confirmation. | Done | `tests/test_workflow_orchestration.py::test_confirmed_manual_buy_sends_one_manual_signal_to_the_broker` |
| 13 | Full Cycle and Intraday still send only `survivors` to news, AI, composite scoring and automatic decisions. | Superseded | The owner ruled on 2026-10-31 that Intraday keeps sending held positions that failed the technical filter to news and AI, so each gets an exit decision (`b_application/pipeline.py`, `run_intraday`), and `docs/requirements.md` notes the exception under US-005. Full Cycle sends only survivors (`tests/test_workflow_orchestration.py::test_full_cycle_saves_only_survivors_as_technical_and_never_orders`). |
| 14 | `TechnicalFilter` has no manual-mode or workflow-specific behavior. | Done | `tests/test_workflow_orchestration.py::test_full_cycle_saves_only_survivors_as_technical_and_never_orders` and `tests/test_workflow_orchestration.py::test_specific_stock_analysis_returns_manual_watchlist_candidates_without_orders` give the same two stocks the same result in menu 1 and menu 4. |
| 15 | `AiAnalyser` does not decide technical eligibility. The calling workflow does. | Done | `tests/test_workflow_orchestration.py::test_specific_stock_analysis_returns_manual_watchlist_candidates_without_orders` analyses the failing stock that menu 4 passes in, and `tests/test_workflow_orchestration.py::test_full_cycle_saves_only_survivors_as_technical_and_never_orders` analyses only the survivor that Full Cycle passes in. |

## US-006 Short-term social buzz workflow

| # | Criterion | Status | Evidence |
| --- | --- | --- | --- |
| 1 | `BuzzScanner` gets the recently discussed stocks. | Done | `tests/test_buzz_scanner.py::test_ptt_pages_back_through_the_search_until_a_post_is_older_than_the_lookback`, `tests/test_workflow_orchestration.py::test_buzz_scan_persists_only_technical_survivors` |
| 2 | Buzz uses its own strategy, not the active Full Cycle strategy. | Done | `tests/test_technical_strategy_selection.py::test_buzz_runs_the_saved_buzz_strategy_and_every_other_workflow_the_saved_active_one`. Buzz reads the owner's `buzz_strategy_id`, which starts as `balanced` since 2026-11-03. |
| 3 | Daily OHLCV is loaded and technical indicators are calculated. | Done | `tests/test_workflow_orchestration.py::test_buzz_scan_persists_only_technical_survivors` requests the history of both stocks, and the Buzz strategy decides on it. |
| 4 | Buzz hard failures are only minimum price, minimum liquidity and maximum daily range. | Superseded | The owner's 2026-11-03 ruling (`docs/strategy-implementation-handoff-2026-11-03.zh-TW.md`) replaced criteria classes with formulas the user composes, and ships three built-in strategies: Conservative, Balanced and Aggressive. No built-in Buzz strategy ships; an owner builds one from formulas and selects it as `buzz_strategy_id` (`tests/test_web_api.py::test_a_save_replaces_the_settings_raises_the_revision_and_drives_the_next_run`). |
| 5 | RSI, volume expansion, MACD and Stochastic only lower the technical quality. | Superseded | The owner's 2026-11-03 ruling (`docs/strategy-implementation-handoff-2026-11-03.zh-TW.md`) replaced criteria classes with formulas the user composes, and ships three built-in strategies. A rule's effect (`reduce_score_on_fail`) is the user's choice per rule (`tests/test_technical_formula.py::test_failures_and_bonuses_of_several_rules_add_up`). |
| 6 | Stocks that pass the Buzz hard rules are saved as `WatchlistType.BUZZ`. | Done | `tests/test_workflow_orchestration.py::test_buzz_scan_persists_only_technical_survivors` |
| 7 | News and social posts are analysed with the momentum AI prompt. | Done | `tests/test_workflow_orchestration.py::test_buzz_scan_persists_only_technical_survivors` asks the AI with focus `MOMENTUM`, and `tests/test_workflow_orchestration.py::test_second_buzz_scan_in_a_session_prompts_only_current_discussions` finds the post title in the prompt. |
| 8 | The technical score and the composite score are calculated. | Done | `tests/test_workflow_orchestration.py::test_buzz_scan_orders_only_when_market_is_open_and_quote_is_fresh` generates a BUY, which needs a composite score. |
| 9 | Trading signals are generated and persisted. | Done | `tests/test_workflow_orchestration.py::test_buzz_scan_orders_only_when_market_is_open_and_quote_is_fresh` |
| 10 | `OrderExecution` receives the executable signals. | Done | `tests/test_workflow_orchestration.py::test_buzz_scan_orders_only_when_market_is_open_and_quote_is_fresh` |
| 11 | Order validation still owns the market-open, quantity, price, cash and broker checks. | Done | `tests/test_workflow_orchestration.py::test_buzz_scan_orders_only_when_market_is_open_and_quote_is_fresh` sends nothing for a closed market or a stale quote, and `tests/test_mock_execution_provider.py::test_business_refusals_are_rejected_before_acceptance` refuses a BUY the cash cannot pay. |
| 12 | The workflow returns a complete `PipelineStatus`. | Done | `tests/test_workflow_orchestration.py::test_buzz_scan_never_analyses_stocks_below_both_buzz_thresholds`, `tests/test_workflow_orchestration.py::test_buzz_scan_orders_only_when_market_is_open_and_quote_is_fresh` |

## US-007 Apply social buzz thresholds

| # | Criterion | Status | Evidence |
| --- | --- | --- | --- |
| 1 | Social posts are grouped by `stock_id`. | Done | `tests/test_buzz_scanner.py::test_a_stock_qualifies_by_mention_count_or_by_engagement` |
| 2 | Each stock gets a `mention_count`. | Done | `tests/test_buzz_scanner.py::test_a_stock_qualifies_by_mention_count_or_by_engagement` qualifies a stock on 20 mentions. |
| 3 | Each stock gets an engagement metric. | Done | `tests/test_buzz_scanner.py::test_a_stock_qualifies_by_mention_count_or_by_engagement`, `tests/test_buzz_scanner.py::test_ptt_post_engagement_counts_every_push_boo_and_arrow` |
| 4 | The configured Buzz thresholds apply. | Done | `tests/test_buzz_scanner.py::test_a_stock_qualifies_by_mention_count_or_by_engagement`, `tests/test_buzz_scanner.py::test_engagement_one_below_the_threshold_does_not_qualify` |
| 5 | The existing `SocialBuzzCriteria` decides eligibility. | Done | `tests/test_buzz_scanner.py::test_a_stock_qualifies_by_mention_count_or_by_engagement`. The method is now `SocialBuzzCriteria.apply` (`a_domain/rules/collect/social_buzz_criteria.py:21`), not `is_trending()`. |
| 6 | Stocks below both thresholds do not enter the US-006 analysis. | Done | `tests/test_workflow_orchestration.py::test_buzz_scan_never_analyses_stocks_below_both_buzz_thresholds` |
| 7 | Every qualifying post stays attached to its stock. | Done | `tests/test_buzz_scanner.py::test_a_stock_qualifies_by_mention_count_or_by_engagement` keeps 20 posts and 1 post. |
| 8 | The statistics record the stock count before and after the Buzz filter. | Done | `tests/test_buzz_scanner.py::test_a_stock_qualifies_by_mention_count_or_by_engagement`, `tests/test_social_sentiment.py::test_menu_2_reports_sentiment_of_qualified_posts_only_and_trades_the_same_either_way` prints `Buzz Filter: Discussed=2, Qualified=1`. |
| 9 | The US-006 technical, AI, watchlist, signal and order behavior is unchanged. | Done | `tests/test_workflow_orchestration.py::test_buzz_scan_persists_only_technical_survivors`, `tests/test_workflow_orchestration.py::test_buzz_scan_orders_only_when_market_is_open_and_quote_is_fresh` |

## US-008 Complete the intraday trading workflow

| # | Criterion | Status | Evidence |
| --- | --- | --- | --- |
| 1 | Each run creates a new `PipelineStatus`. | Done | `tests/test_trading_journal_reads.py::test_recent_runs_come_newest_first_up_to_the_limit` records three Intraday runs under three run IDs. |
| 2 | The workflow loads the account cash and positions. | Done | `tests/test_workflow_orchestration.py::test_intraday_loads_held_positions_and_active_watchlist`, `tests/test_workflow_orchestration.py::test_one_runs_buys_risk_a_share_of_the_equity_best_score_first_until_the_cash_runs_out` |
| 3 | The workflow loads the active watchlist. | Done | `tests/test_stock_candidates.py::test_intraday_candidates_are_held_stocks_plus_the_active_watchlist` |
| 4 | Held and watched stocks merge, one per `stock_id`. | Done | `tests/test_stock_candidates.py::test_intraday_candidates_are_held_stocks_plus_the_active_watchlist`, `tests/test_workflow_orchestration.py::test_intraday_loads_held_positions_and_active_watchlist` |
| 5 | The workflow fetches intraday or latest market data. | Done | `tests/test_market_data_freshness.py::test_a_fresh_quote_is_not_asked_for_again_and_clears_the_stale_mark`, `tests/test_mis_quote_provider.py::test_each_quote_is_the_session_so_far_closing_at_the_last_trade_at_its_trade_time` |
| 6 | The workflow checks data freshness. | Done | `tests/test_workflow_orchestration.py::test_intraday_places_no_order_for_a_stale_quote` |
| 7 | The workflow recalculates the technical indicators. | Done | `tests/test_workflow_orchestration.py::test_intraday_loads_held_positions_and_active_watchlist` passes both stocks on a moving-average rule from their daily history. `tests/test_technical_indicator_calculator.py::test_calculator_uses_configurable_indicator_periods` |
| 8 | The workflow runs technical, news and AI analysis. | Done | `tests/test_workflow_orchestration.py::test_intraday_loads_held_positions_and_active_watchlist` asserts the technical filter and the AI calls. `tests/test_workflow_orchestration.py::test_intraday_fetches_each_candidates_news_and_gives_it_to_the_ai` finds the news headline in the AI prompt. |
| 9 | The workflow generates trading signals. | Done | `tests/test_workflow_orchestration.py::test_order_execution_skips_closed_market_orders` |
| 10 | The workflow executes the allowed orders. | Done | `tests/test_workflow_orchestration.py::test_order_execution_skips_closed_market_orders` sends the order while the market is open and sends nothing after the close. |
| 11 | The workflow saves its decisions and execution results. | Done | `tests/test_workflow_orchestration.py::test_intraday_records_each_decision_and_the_brokers_answer_to_its_order` finds the decision, the `FILLED` order under its run and decision IDs, and the run record's order count in the journal. |
| 12 | The workflow returns a complete `PipelineStatus`. | Done | `tests/test_workflow_orchestration.py::test_intraday_loads_held_positions_and_active_watchlist`, `tests/test_workflow_orchestration.py::test_intraday_places_no_order_for_a_stale_quote` |

## US-009 Control the automatic order mode explicitly

| # | Criterion | Status | Evidence |
| --- | --- | --- | --- |
| 1 | `OrderMode.DISABLED` sends no order at all. | Done | `tests/test_order_rule.py::test_each_gate_rejects_with_its_reason`, `tests/test_trading_audit.py::test_a_refused_manual_buy_is_a_recorded_rejected_order_with_its_reason` leaves the cash unchanged. |
| 2 | `OrderMode.MOCK_ONLY` allows only `MockExecutionProvider`. | Done | `tests/test_trading_startup.py::test_each_environment_provider_and_order_mode_either_starts_or_is_refused`, `tests/test_order_rule.py::test_each_gate_rejects_with_its_reason` |
| 3 | `OrderMode.LIVE` allows only an explicitly configured real broker. | Done | `tests/test_trading_startup.py::test_each_environment_provider_and_order_mode_either_starts_or_is_refused`, `tests/test_order_rule.py::test_each_gate_rejects_with_its_reason` |
| 4 | Full Cycle places no order by default. | Done | `tests/test_workflow_orchestration.py::test_full_cycle_saves_only_survivors_as_technical_and_never_orders`. Full Cycle never orders, even with the market open. |
| 5 | Buzz and Intraday follow the order mode before they call `OrderExecution`. | Done | `tests/test_workflow_orchestration.py::test_buzz_and_intraday_send_an_order_only_when_the_order_mode_allows_it` runs menus 2 and 3 under `disabled`, `mock_only` and `live`. A mismatched order mode never reaches a menu, because startup refuses it (`tests/test_trading_startup.py::test_each_environment_provider_and_order_mode_either_starts_or_is_refused`). |
| 6 | The CLI shows the current execution provider and order mode. | Done | `tests/test_trading_startup.py::test_the_menu_header_warns_about_a_real_broker`, `tests/test_trading_startup.py::test_menus_2_3_and_4_say_they_may_submit_orders_under_the_current_order_mode` |
| 7 | No second boolean duplicates the order mode. | Done | `tests/test_trading_startup.py::test_the_order_mode_is_the_only_setting_that_turns_orders_on_or_off` lists every boolean setting, none of which switches orders, and fails on a new one. |

## US-010 Keep AI analysis and trading decision history

| # | Criterion | Status | Evidence |
| --- | --- | --- | --- |
| 1 | Every generated `TradeSignal` can be saved to the knowledge repository. | Done | `tests/test_decision_history.py::test_decision_history_returns_only_that_stocks_decisions_newest_first` |
| 2 | The saved record has the stock, the score, the signal, the reason and the time. | Done | `tests/test_decision_history.py::test_decision_history_returns_only_that_stocks_decisions_newest_first` |
| 3 | `DecisionMemory` runs in every workflow that generates signals. | Done | `tests/test_workflow_orchestration.py::test_every_workflow_that_decides_hands_each_decision_to_the_knowledge_repository` runs Full Cycle, Buzz, Intraday and Manual BUY. |
| 4 | One failed save does not stop the batch. | Done | `tests/test_decision_history.py::test_one_failed_save_does_not_stop_the_other_decisions` |
| 5 | The next analysis of the stock gets its history. | Done | `tests/test_decision_history.py::test_ai_analysis_prompt_carries_the_analysed_stocks_own_history` |

## US-011 Social sentiment analysis

| # | Criterion | Status | Evidence |
| --- | --- | --- | --- |
| 1 | Sentiment analysis reads the social posts of a qualified trending stock. | Done | `tests/test_social_sentiment.py::test_menu_2_reports_sentiment_of_qualified_posts_only_and_trades_the_same_either_way`, `tests/test_social_sentiment.py::test_sentiment_reads_only_social_posts_and_records_a_failed_stock` |
| 2 | Each result has a sentiment label and a confidence. | Done | `tests/test_social_sentiment.py::test_a_post_is_classified_once_and_then_served_from_the_cache` |
| 3 | Post results aggregate into one stock-level sentiment. | Done | `tests/test_social_sentiment.py::test_stock_level_consensus` |
| 4 | Equal bullish and bearish opinions read as disagreement, not as neutral. | Done | `tests/test_social_sentiment.py::test_stock_level_consensus` |
| 5 | The stock-level result has bullish, bearish and neutral ratios and a consensus or disagreement. | Done | `tests/test_social_sentiment.py::test_ratios_are_shares_of_opinions_and_low_confidence_counts_as_unclear`, `tests/test_social_sentiment.py::test_stock_level_consensus` |
| 6 | The model sits behind a replaceable interface. | Done | `tests/test_social_sentiment.py::test_the_sentiment_settings_decide_the_consensus` runs `SentimentAnalyser` with another classifier in place of `AiSentimentClassifier`. |
| 7 | The model can be a pretrained, fine-tuned, small local or external one. | Done | `tests/test_social_sentiment.py::test_a_post_is_classified_once_and_then_served_from_the_cache`. The shipped `AiSentimentClassifier` sends the posts to the configured AI provider, an external inference service. |
| 8 | Client devices do not run the model. | Done | `tests/test_social_sentiment.py::test_menu_2_reports_sentiment_of_qualified_posts_only_and_trades_the_same_either_way`. The backend workflow computes the table that the CLI prints. |
| 9 | Sentiment results can be cached and persisted. | Done | `tests/test_social_sentiment.py::test_a_post_is_classified_once_and_then_served_from_the_cache` reads the second result from the SQLite `SentimentRepository`. |
| 10 | Sentiment never creates a BUY or SELL decision. | Done | `tests/test_social_sentiment.py::test_trading_code_never_reads_sentiment`, `tests/test_social_sentiment.py::test_menu_2_reports_sentiment_of_qualified_posts_only_and_trades_the_same_either_way` |

## US-101 Fetch stock fundamentals

| # | Criterion | Status | Evidence |
| --- | --- | --- | --- |
| 1 | The latest filed EPS can be fetched. | Done | `tests/test_trailing_eps.py::test_ttm_uses_the_newest_quarter_the_company_has_filed`, `tests/test_valuation_pipeline.py::test_market_load_values_every_stock_from_filings_and_official_closes` |
| 2 | Each EPS states its kind: single quarter, cumulative, annual or TTM. | Done | `tests/test_trailing_eps.py::test_eps_text_always_carries_its_period_kind_basis_and_source`. `EpsKind` has all four kinds (`a_domain/types/enums.py:218-234`), and the app computes only TTM. |
| 3 | The financial period is recorded. | Done | `tests/test_trailing_eps.py::test_eps_text_always_carries_its_period_kind_basis_and_source` |
| 4 | The data source is recorded. | Done | `tests/test_trailing_eps.py::test_eps_text_always_carries_its_period_kind_basis_and_source` |
| 5 | The fetch time is recorded. | Done | `tests/test_trailing_eps.py::test_eps_text_always_carries_its_period_kind_basis_and_source` |
| 6 | Missing data is unavailable, not zero. | Done | `tests/test_trailing_eps.py::test_stock_without_any_filing_is_unavailable_not_zero`, `tests/test_trailing_eps.py::test_stock_eps_defaults_to_unavailable_not_zero`, `tests/test_valuation_pipeline.py::test_failed_quarter_is_reported_and_never_turns_into_zero` |
| 7 | The AI never fills in a missing figure. | Done | `tests/test_valuation_pipeline.py::test_numbers_come_from_the_domain_and_never_from_the_ai` drops the `eps` and `fair_price` the AI sends. `tests/test_valuation_domain.py::test_missing_eps_report_says_data_is_insufficient` |

## US-102 Show the EPS

| # | Criterion | Status | Evidence |
| --- | --- | --- | --- |
| 1 | The report shows the EPS value. | Done | `tests/test_valuation_pipeline.py::test_menu_5_reports_each_stock_and_rejects_invalid_targets` prints `86.28 TWD (TTM, 2025Q3–2026Q2, actual, MOPS`. |
| 2 | The report shows the EPS period. | Done | `tests/test_valuation_pipeline.py::test_menu_5_reports_each_stock_and_rejects_invalid_targets` |
| 3 | The report shows whether the EPS is actual or an estimate. | Done | `tests/test_valuation_pipeline.py::test_menu_5_reports_each_stock_and_rejects_invalid_targets` |
| 4 | The report shows the data source. | Done | `tests/test_valuation_pipeline.py::test_menu_5_reports_each_stock_and_rejects_invalid_targets` |
| 5 | Without an EPS the report shows "insufficient data". | Done | `tests/test_valuation_domain.py::test_missing_eps_report_says_data_is_insufficient`, `tests/test_valuation_pipeline.py::test_menu_5_reports_each_stock_and_rejects_invalid_targets`. The text is English, see [Owner decisions](#owner-decisions). |
| 6 | The report never shows the number without its period. | Done | `tests/test_trailing_eps.py::test_eps_text_always_carries_its_period_kind_basis_and_source`. `Eps.describe` is the only text form of an EPS (`a_domain/model/fundamentals/eps.py:46-51`), and the scan table puts the period in its own column. |

## US-103 Calculate the current P/E

| # | Criterion | Status | Evidence |
| --- | --- | --- | --- |
| 1 | The calculation uses an explicit EPS kind, TTM for the MVP. | Done | `tests/test_valuation_domain.py::test_current_pe_is_price_over_ttm_eps`, `tests/test_valuation_pipeline.py::test_market_load_values_every_stock_from_filings_and_official_closes` |
| 2 | The price must be greater than zero. | Done | `tests/test_valuation_domain.py::test_current_pe_outcomes_are_a_closed_set` reads a missing price as `no valid price`, and `tests/test_twse_provider.py::test_a_zero_close_is_no_close` turns a zero close into no price. |
| 3 | A normal P/E is calculated only when the EPS is above zero. | Done | `tests/test_valuation_domain.py::test_current_pe_is_price_over_ttm_eps`, `tests/test_valuation_domain.py::test_current_pe_outcomes_are_a_closed_set` |
| 4 | An EPS of zero shows that the P/E cannot be calculated. | Done | `tests/test_valuation_domain.py::test_current_pe_outcomes_are_a_closed_set` |
| 5 | A negative EPS shows a loss, with the P/E not applicable. | Done | `tests/test_valuation_domain.py::test_current_pe_outcomes_are_a_closed_set` |
| 6 | A domain rule calculates the P/E, not the AI. | Done | `tests/test_valuation_pipeline.py::test_numbers_come_from_the_domain_and_never_from_the_ai` hands the AI the domain's `27.99x`. |
| 7 | The report shows the time of the price it used. | Done | `tests/test_valuation_pipeline.py::test_menu_5_reports_each_stock_and_rejects_invalid_targets` prints `2,415.00 TWD (2026-10-29 close, published by the exchange)`. |

## US-104 Ask the user for a target P/E

| # | Criterion | Status | Evidence |
| --- | --- | --- | --- |
| 1 | The CLI asks for the target P/E. | Done | `tests/test_valuation_pipeline.py::test_menu_5_reports_each_stock_and_rejects_invalid_targets` |
| 2 | The input must be a finite number greater than zero. | Done | `tests/test_valuation_pipeline.py::test_menu_5_reports_each_stock_and_rejects_invalid_targets` refuses `abc`, `0` and `inf`. `tests/test_valuation_domain.py::test_target_pe_must_be_finite_and_positive` |
| 3 | The user can cancel. | Done | `tests/test_valuation_pipeline.py::test_menu_5_blank_target_cancels_before_any_ai_call` |
| 4 | The current market P/E is shown for reference. | Done | `tests/test_valuation_pipeline.py::test_menu_6_scans_confirms_technically_and_explains_the_survivor` prints `Market median P/E for reference`. `tests/test_valuation_domain.py::test_median_pe_uses_fresh_computable_ratios_only`. Menu 5 prints the same line (`d_presentation/cli/valuation_views.py:183`) next to each stock's own P/E. |
| 5 | The industry is shown, and the MVP does not pick an industry P/E. | Driven | `valuation.md: value-report`, driven 2026-10-31 on 59ba50d (`~/.cache/stock-agent-verify-final/evidence/fd-valuation/menu5-value-2330-0050/transcript.txt`): the `Valuation Facts` table has an `Industry` column and an `Industry median P/E` reference, and the target P/E is the one the user typed. `tests/test_valuation_domain.py::test_median_pe_uses_fresh_computable_ratios_only` covers the median. |
| 6 | The input applies only to this analysis unless the user asks to save it. | Done | `tests/test_valuation_pipeline.py::test_valuation_menus_never_place_orders_or_write_the_watchlist` asks the target again in menu 6 after menu 5, and records nothing. |

## US-105 Calculate the fair price

| # | Criterion | Status | Evidence |
| --- | --- | --- | --- |
| 1 | The calculation uses the EPS and the user's target P/E. | Done | `tests/test_valuation_domain.py::test_fair_price_scenarios_follow_eps_times_target_pe` |
| 2 | The report shows the fair price. | Done | `tests/test_valuation_domain.py::test_report_text_shows_every_scenario_with_its_assumption` |
| 3 | The report shows the current price. | Done | `tests/test_valuation_domain.py::test_every_report_lists_all_us_107_items`, `tests/test_valuation_pipeline.py::test_menu_5_reports_each_stock_and_rejects_invalid_targets` |
| 4 | The report shows the price gap. | Done | `tests/test_valuation_domain.py::test_report_text_shows_every_scenario_with_its_assumption` prints `Base gap -258.00 TWD`. |
| 5 | The report shows the undervaluation or overvaluation percentage. | Done | `tests/test_valuation_domain.py::test_report_text_shows_every_scenario_with_its_assumption` prints `overvalued by 10.7%`. |
| 6 | The model is not used when the EPS is zero or below. | Done | `tests/test_valuation_domain.py::test_no_fair_price_when_eps_is_not_positive_or_missing` |
| 7 | The result is labelled "a valuation based on a specified P/E", never an objective true value. | Done | `tests/test_valuation_pipeline.py::test_menu_5_reports_each_stock_and_rejects_invalid_targets` prints the label on every panel. `tests/test_valuation_domain.py::test_every_report_lists_all_us_107_items` checks the fixed statement that the result is not an objective true value. The text is English, see [Owner decisions](#owner-decisions). |

## US-106 Show a fair-price range

| # | Criterion | Status | Evidence |
| --- | --- | --- | --- |
| 1 | Three target P/Es are supported: conservative, base and optimistic. | Done | `tests/test_valuation_domain.py::test_fair_price_scenarios_follow_eps_times_target_pe` |
| 2 | Each of the three gets its own fair price. | Done | `tests/test_valuation_domain.py::test_fair_price_scenarios_follow_eps_times_target_pe` |
| 3 | Each P/E comes from a setting, the user's input or an explicit rule. | Done | `tests/test_valuation_domain.py::test_report_text_shows_every_scenario_with_its_assumption` takes the base from the user and the other two from `valuation.scenario_spread`. |
| 4 | The AI can explain the scenarios but cannot change the numbers. | Done | `tests/test_valuation_pipeline.py::test_numbers_come_from_the_domain_and_never_from_the_ai` |
| 5 | The report shows the assumption of each scenario. | Done | `tests/test_valuation_domain.py::test_report_text_shows_every_scenario_with_its_assumption` |

## US-107 AI explanation of the valuation

Rows 1 to 10 are the items the AI report must contain. Rows 11 to 14 are what the AI must not do.

| # | Criterion | Status | Evidence |
| --- | --- | --- | --- |
| 1 | The current price. | Done | `tests/test_valuation_domain.py::test_every_report_lists_all_us_107_items` |
| 2 | The EPS and its reporting period. | Done | `tests/test_valuation_domain.py::test_every_report_lists_all_us_107_items` |
| 3 | The current P/E. | Done | `tests/test_valuation_domain.py::test_every_report_lists_all_us_107_items` |
| 4 | The user's target P/E. | Done | `tests/test_valuation_domain.py::test_every_report_lists_all_us_107_items` |
| 5 | The derived fair price. | Done | `tests/test_valuation_domain.py::test_every_report_lists_all_us_107_items` |
| 6 | The overvaluation or undervaluation percentage. | Done | `tests/test_valuation_domain.py::test_every_report_lists_all_us_107_items` |
| 7 | Factors that may support a higher P/E. | Done | `tests/test_valuation_domain.py::test_every_report_lists_all_us_107_items`, `tests/test_valuation_pipeline.py::test_numbers_come_from_the_domain_and_never_from_the_ai` prints the AI's factors. |
| 8 | Risks that may lower the P/E. | Done | `tests/test_valuation_domain.py::test_every_report_lists_all_us_107_items`, `tests/test_valuation_pipeline.py::test_numbers_come_from_the_domain_and_never_from_the_ai` prints the AI's risks. |
| 9 | Insufficient-data warnings. | Done | `tests/test_valuation_domain.py::test_every_report_lists_all_us_107_items`, `tests/test_valuation_pipeline.py::test_failed_ai_call_still_yields_every_report_item` |
| 10 | A not-investment-advice statement. | Done | `tests/test_valuation_domain.py::test_every_report_lists_all_us_107_items` |
| 11 | The AI must not create an EPS. | Done | `tests/test_valuation_pipeline.py::test_numbers_come_from_the_domain_and_never_from_the_ai` drops the `eps: 123.45` the AI sends. |
| 12 | The AI must not present speculation from the news as official financial data. | Driven | `valuation.md: value-report`, driven 2026-11-01 on d931761 with the real AI key (`~/.cache/stock-agent-verify-guidefix-ai/evidence/fd-valuation/menu5-value-2330-0050/transcript.txt`, line 120): the AI writes `News items are opinions and forecasts, not official financial statements, and were not treated as valuation inputs`, and every number row comes from the domain (`tests/test_valuation_pipeline.py::test_numbers_come_from_the_domain_and_never_from_the_ai`). The a761439 drive said the same in other words. |
| 13 | The AI must not give a precise fair price when data is missing. | Done | `tests/test_valuation_pipeline.py::test_loss_making_stock_never_asks_the_ai_for_a_fair_price`, `tests/test_valuation_domain.py::test_no_fair_price_when_eps_is_not_positive_or_missing` |
| 14 | The AI must not present one valuation formula as the only correct answer. | Driven | `valuation.md: value-report`, driven 2026-11-01 on d931761 with the real AI key (`~/.cache/stock-agent-verify-guidefix-ai/evidence/fd-valuation/menu5-value-2330-0050/transcript.txt`, line 119): the AI says the target multiple is a user input and the other cases come from a model spread setting, not a consensus value, and the fixed statement reads `The result depends on the assumed P/E and is not an objective true value`, checked by `tests/test_valuation_domain.py::test_every_report_lists_all_us_107_items`. |

## US-108 Find stocks undervalued on P/E

| # | Criterion | Status | Evidence |
| --- | --- | --- | --- |
| 1 | The user enters a target P/E. | Done | `tests/test_valuation_pipeline.py::test_menu_6_scans_confirms_technically_and_explains_the_survivor` |
| 2 | The system loads the stock list. | Done | `tests/test_valuation_pipeline.py::test_market_load_values_every_stock_from_filings_and_official_closes` |
| 3 | The system gets the latest price and EPS of each stock. | Done | `tests/test_valuation_pipeline.py::test_market_load_values_every_stock_from_filings_and_official_closes` |
| 4 | The scan excludes a missing EPS, an EPS of zero or below, and a stale price. | Done | `tests/test_valuation_domain.py::test_screen_keeps_undervalued_stocks_sorted_and_records_why_others_left` |
| 5 | The scan calculates the current P/E. | Done | `tests/test_valuation_pipeline.py::test_market_load_values_every_stock_from_filings_and_official_closes` |
| 6 | The scan calculates the fair price. | Done | `tests/test_valuation_domain.py::test_screen_keeps_undervalued_stocks_sorted_and_records_why_others_left`, `tests/test_valuation_domain.py::test_fair_price_scenarios_follow_eps_times_target_pe` |
| 7 | The scan calculates the undervaluation. | Done | `tests/test_valuation_domain.py::test_screen_keeps_undervalued_stocks_sorted_and_records_why_others_left` |
| 8 | The scan keeps only the stocks that meet the user's criteria. | Done | `tests/test_valuation_domain.py::test_screen_keeps_undervalued_stocks_sorted_and_records_why_others_left` |
| 9 | The scan sorts by undervaluation. | Done | `tests/test_valuation_domain.py::test_screen_keeps_undervalued_stocks_sorted_and_records_why_others_left` |
| 10 | The result shows the code, name, price, EPS, current P/E, target P/E, fair price, undervaluation, financial period and source. | Driven | `valuation.md: scan-valuation`, driven 2026-10-31 on 59ba50d (`~/.cache/stock-agent-verify-final/evidence/fd-valuation/menu6-scan-technical/transcript.txt`): the table header holds Stock, Name, Close (session), EPS, Current P/E, Target P/E, Fair price, Undervalued, EPS period and Source. |

## US-109 Combine valuation and technical screening

| # | Criterion | Status | Evidence |
| --- | --- | --- | --- |
| 1 | The valuation screen and the technical screen are two explicit steps. | Done | `tests/test_valuation_pipeline.py::test_menu_6_scans_confirms_technically_and_explains_the_survivor` prints `Two-step screen: valuation -> technical (trend)`. `tests/test_valuation_pipeline.py::test_scan_then_technical_step_records_where_each_stock_left` |
| 2 | The result shows the step that eliminated each stock. | Done | `tests/test_valuation_pipeline.py::test_scan_then_technical_step_records_where_each_stock_left`, `tests/test_valuation_pipeline.py::test_menu_6_scans_confirms_technically_and_explains_the_survivor` |
| 3 | A stock must have a valid EPS, pass the valuation and have no technical hard failure. | Done | `tests/test_valuation_domain.py::test_technical_step_eliminates_hard_failures_and_missing_history_only`, `tests/test_valuation_domain.py::test_screen_keeps_undervalued_stocks_sorted_and_records_why_others_left` |
| 4 | A low P/E is never treated as a BUY. | Done | `tests/test_valuation_pipeline.py::test_valuation_menus_never_place_orders_or_write_the_watchlist` |
| 5 | The AI report explains that a low P/E can come from falling growth or market risk. | Done | `tests/test_valuation_pipeline.py::test_undervalued_stock_prompt_asks_the_ai_to_explain_low_pe_causes`, `tests/test_valuation_domain.py::test_undervalued_report_carries_the_low_pe_caveat` |

## US-201 Check realtime data freshness

| # | Criterion | Status | Evidence |
| --- | --- | --- | --- |
| 1 | The Intraday workflow uses `DataFreshnessRule`. | Done | `tests/test_workflow_orchestration.py::test_intraday_places_no_order_for_a_stale_quote` |
| 2 | Stale data never produces an executable BUY order. | Done | `tests/test_workflow_orchestration.py::test_intraday_places_no_order_for_a_stale_quote`, `tests/test_workflow_orchestration.py::test_buzz_scan_orders_only_when_market_is_open_and_quote_is_fresh`, `tests/test_order_rule.py::test_a_quote_fresh_when_fetched_is_refused_once_it_aged_past_the_limit` |
| 3 | Stale data is counted in the stats. | Done | `tests/test_market_data_freshness.py::test_a_failed_quote_fetch_blocks_every_asked_stock_once`, `tests/test_market_data_freshness.py::test_daily_history_older_than_the_history_limit_is_not_analysed` |
| 4 | The report shows the time of the latest data. | Driven | `intraday.md: intraday-stale-block`, driven 2026-10-31 on 59ba50d (`~/.cache/stock-agent-verify-final/evidence/fd-intraday/intraday/transcript.txt`): `Blocked Stale Market Data` lists `2330 │ 2026-10-30 13:30` under `Last Data Time`. |
| 5 | Historical analysis and realtime trading use different freshness limits. | Done | `tests/test_market_data_freshness.py::test_realtime_quotes_use_the_minute_limit_not_the_day_limit`, `tests/test_market_data_freshness.py::test_daily_history_older_than_the_history_limit_is_not_analysed` |

## US-202 Include trading fees and tax

| # | Criterion | Status | Evidence |
| --- | --- | --- | --- |
| 1 | A BUY pays the fee. | Done | `tests/test_trading_cost.py::test_buy_pays_gross_plus_fee_rounded_down_and_no_tax` |
| 2 | A SELL pays the fee and the transaction tax. | Done | `tests/test_trading_cost.py::test_sell_receives_gross_minus_fee_and_transaction_tax`, `tests/test_trading_cost.py::test_a_sell_pays_the_stock_rate_on_a_stock_the_etf_rate_on_an_etf_and_nothing_on_a_bond_etf_until_its_exemption_ends` |
| 3 | The minimum fee applies. | Done | `tests/test_trading_cost.py::test_small_trade_pays_the_minimum_fee` |
| 4 | `SizingRule` leaves room for the trading cost. | Done | `tests/test_sizing.py::test_quantity_is_the_equity_risk_budget_capped_by_cash_after_fees`, `tests/test_trading_cost.py::test_the_affordable_quantity_leaves_room_for_the_fee` |
| 5 | The order result keeps the actual cost. | Done | `tests/test_trading_audit.py::test_an_order_row_traces_back_to_its_price_reports_signal_run_and_result` reads fee 285 and tax 0 from the `orders` row. |
| 6 | Realized PnL includes the fees and the tax. | Done | `tests/test_mock_execution_provider.py::test_sell_realizes_pnl_net_of_both_fees_and_the_tax` |

## US-203 Keep account and position snapshots

| # | Criterion | Status | Evidence |
| --- | --- | --- | --- |
| 1 | A cash snapshot is saved. | Done | `tests/test_trading_audit.py::test_an_order_row_traces_back_to_its_price_reports_signal_run_and_result` |
| 2 | A position snapshot is saved. | Done | `tests/test_trading_audit.py::test_an_order_row_traces_back_to_its_price_reports_signal_run_and_result` |
| 3 | Each filled order creates a snapshot. | Done | `tests/test_trading_audit.py::test_an_order_row_traces_back_to_its_price_reports_signal_run_and_result` finds the snapshot by the order's ID. |
| 4 | The account can be read as of a given date. | Done | `tests/test_account_history.py::test_the_account_as_of_a_day_is_its_last_fill_marked_at_that_days_close` |
| 5 | The equity curve can be calculated. | Done | `tests/test_account_history.py::test_the_equity_curve_marks_each_trading_day_at_its_close` |
| 6 | Unrealized PnL can be calculated. | Done | `tests/test_account_history.py::test_current_positions_are_marked_at_the_latest_quote_net_of_exit_costs` |

## US-204 Keep an execution audit trail

| # | Criterion | Status | Evidence |
| --- | --- | --- | --- |
| 1 | Each workflow run has a unique run ID. | Done | `tests/test_trading_journal_reads.py::test_recent_runs_come_newest_first_up_to_the_limit`, `tests/test_workflow_orchestration.py::test_a_workflow_started_under_a_named_run_id_records_under_it` |
| 2 | Each signal has a unique decision ID. | Done | `tests/test_trading_audit.py::test_an_order_row_traces_back_to_its_price_reports_signal_run_and_result` finds the one signal row by the order's decision ID, the key of `trade_signals`. |
| 3 | Each order keeps its run ID and decision ID. | Done | `tests/test_order_rule.py::test_a_fresh_decision_becomes_a_pending_ioc_limit_order_at_its_price`, `tests/test_web_api.py::test_orders_of_a_run_carry_status_reason_costs_and_ids` |
| 4 | An order traces back to its stock data, technical analysis, AI report, signal and execution result. | Done | `tests/test_trading_audit.py::test_an_order_row_traces_back_to_its_price_reports_signal_run_and_result` |

## US-205 Support the full order lifecycle

| # | Criterion | Status | Evidence |
| --- | --- | --- | --- |
| 1 | Each status has legal transitions. | Done | `tests/test_order_lifecycle.py::test_every_status_change_is_legal_only_if_the_lifecycle_allows_it` |
| 2 | An illegal transition fails. | Done | `tests/test_order_lifecycle.py::test_every_status_change_is_legal_only_if_the_lifecycle_allows_it` |
| 3 | ROD, IOC and FOK each have a defined behavior. | Done | `tests/test_mock_execution_provider.py::test_ioc_fills_what_the_market_can_take_and_cancels_the_rest`, `tests/test_mock_execution_provider.py::test_fok_fills_everything_or_nothing`, `tests/test_mock_execution_provider.py::test_rod_is_rejected_because_nothing_could_fill_its_working_remainder`, `tests/test_shioaji_execution_provider.py::test_fok_is_sent_as_fok` |
| 4 | Rejected and failed are clearly different. | Done | `tests/test_mock_execution_provider.py::test_business_refusals_are_rejected_before_acceptance`, `tests/test_mock_execution_provider.py::test_a_technical_error_fails_the_order` |
| 5 | Only an order that is not fully filled can be cancelled. | Done | `tests/test_order_lifecycle.py::test_every_status_change_is_legal_only_if_the_lifecycle_allows_it` refuses to cancel a filled order. `tests/test_order_lifecycle.py::test_cancelling_a_partly_filled_order_keeps_what_was_filled` |
| 6 | Tests cover every status transition. | Done | `tests/test_order_lifecycle.py::test_every_status_change_is_legal_only_if_the_lifecycle_allows_it` tries every pair of source and target status. `tests/test_order_lifecycle.py::test_nothing_moves_an_order_back_to_pending` |

## US-301 Connect the Shioaji broker

| # | Criterion | Status | Evidence |
| --- | --- | --- | --- |
| 1 | The app logs in to Shioaji. | Partial | Untested. `tests/test_shioaji_execution_provider.py::test_simulation_login_uses_the_api_key_pair_and_no_ca` and `tests/test_shioaji_execution_provider.py::test_production_login_activates_the_ca` log in to a fake client modelled on shioaji 1.3.1. No run has logged in to a real Shioaji account, and a drive must not contact Shioaji. |
| 2 | The app reads the real cash. | Partial | Untested. `tests/test_shioaji_execution_provider.py::test_get_account_reads_cash_less_payments_due_and_the_long_cash_positions_in_shares` reads cash from the fake client. No real account has been read. |
| 3 | The app reads the real positions. | Partial | Untested. `tests/test_shioaji_execution_provider.py::test_get_account_reads_cash_less_payments_due_and_the_long_cash_positions_in_shares` reads positions from the fake client. No real account has been read. |
| 4 | A domain `Order` becomes a broker order. | Done | `tests/test_shioaji_execution_provider.py::test_a_whole_lot_buy_is_one_board_lot_limit_order_on_the_logged_in_account`, `tests/test_shioaji_execution_provider.py::test_a_mixed_quantity_is_split_into_a_board_lot_ioc_order_and_an_odd_lot_rod_order` |
| 5 | The broker's answer becomes a domain `Order` again. | Done | `tests/test_shioaji_execution_provider.py::test_every_shioaji_status_has_a_domain_status`, `tests/test_shioaji_execution_provider.py::test_each_final_shioaji_status_ends_the_domain_order`, `tests/test_shioaji_execution_provider.py::test_deals_at_several_prices_fill_at_their_volume_weighted_price` |
| 6 | LIVE mode must be enabled explicitly. | Done | `tests/test_trading_startup.py::test_each_environment_provider_and_order_mode_either_starts_or_is_refused` |
| 7 | `MockExecutionProvider` stays the default. | Done | `tests/test_trading_startup.py::test_the_mock_broker_in_mock_only_mode_is_the_default` |

## US-302 Web API for the trading workflows

| # | Criterion | Status | Evidence |
| --- | --- | --- | --- |
| 1 | The API can start Full Cycle. | Done | `tests/test_web_api.py::test_full_cycle_runs_in_the_background_under_the_run_id_it_returns` |
| 2 | The API can analyse given stocks. | Done | `tests/test_web_api.py::test_specific_stock_analysis_reports_each_requested_stock` |
| 3 | The API can read the watchlist. | Done | `tests/test_web_api.py::test_watchlist_shows_each_entry_with_its_type_and_expiry` |
| 4 | The API can read signals and orders. | Done | `tests/test_web_api.py::test_full_cycle_runs_in_the_background_under_the_run_id_it_returns`, `tests/test_web_api.py::test_orders_of_a_run_carry_status_reason_costs_and_ids` |
| 5 | Writes need permission and confirmation. | Done | `tests/test_web_api.py::test_writes_need_a_session`, `tests/test_web_api.py::test_writes_need_confirm_true`, `tests/test_web_api.py::test_writes_need_the_web_apps_header_so_another_site_cannot_send_them` |
| 6 | The API does not copy domain business rules. | Done | The rule `PRESENTATION-DECIDES-NOTHING` of the checker `tools/architecture_check.py` (run from `backend/`) reports 0 for `src`. It reports a web or CLI module that imports a domain rule or reads a setting outside its allow-list, which for the web layer is the LINE channel secret, and a response class that defines a method. `tests/test_architecture_check.py::test_rule_reports_every_violation_in_its_failing_example` shows that the rule finds each planted violation, and `tests/test_architecture_check.py::test_rule_reports_nothing_in_its_passing_example` that it accepts the allowed reads. `tests/test_web_api.py::test_the_api_refuses_to_start_on_the_trading_setups_the_cli_refuses` shows that the startup checks are shared. |

## US-303 UI for technical parameters

| # | Criterion | Status | Evidence |
| --- | --- | --- | --- |
| 1 | The UI fields match the existing `IndicatorParameters`. | Superseded | The owner's 2026-11-03 ruling (`docs/strategy-implementation-handoff-2026-11-03.zh-TW.md`) replaced criteria classes with formulas the user composes, and ships three built-in strategies. The settings page was removed; the OpenAPI document gives an editor every field and bound, and `indicator-outputs.json` every indicator output, from the server's own definitions (`tests/test_web_api.py::test_the_old_settings_page_and_reset_are_gone`, `tests/test_openapi_snapshot.py`). |
| 2 | Every input is validated. | Done | `tests/test_web_api.py::test_invalid_settings_are_refused_at_their_fields_under_body_settings_and_nothing_is_saved`, `tests/test_web_api.py::test_settings_that_contradict_themselves_are_refused_and_nothing_is_saved`, `tests/test_technical_settings_validation.py::test_invalid_settings_are_refused` |
| 3 | The UI does not change domain objects directly. | Done | A client sends JSON, which the domain model validates as a whole before anything is saved (`tests/test_web_api.py::test_invalid_settings_are_refused_at_their_fields_under_body_settings_and_nothing_is_saved`, `tests/test_technical_settings_repository.py::test_settings_keep_every_formula_through_json_and_sql`). |
| 4 | Saved settings are used by the next workflow. | Done | `tests/test_web_api.py::test_a_save_replaces_the_settings_raises_the_revision_and_drives_the_next_run` |
| 5 | The UI shows the current strategy and its parameters. | Superseded | The owner's 2026-11-03 ruling (`docs/strategy-implementation-handoff-2026-11-03.zh-TW.md`) replaced criteria classes with formulas the user composes, and ships three built-in strategies. No UI ships yet; `GET /v1/technical-settings` returns the owner's strategies, selections and revision (`tests/test_web_api.py::test_the_saved_settings_come_with_the_revision_a_save_must_carry`). |

## US-304 Configurable technical strategy composition

| # | Criterion | Status | Evidence |
| --- | --- | --- | --- |
| 1 | The strategy configuration assigns criteria to `must_pass`, `should_pass` and `observe`. | Superseded | The owner's 2026-11-03 ruling (`docs/strategy-implementation-handoff-2026-11-03.zh-TW.md`) replaced criteria classes with formulas the user composes, and ships three built-in strategies. Each rule's `effect` is `block_on_fail`, `reduce_score_on_fail` or `increase_score_on_pass` (`tests/test_technical_formula.py::test_a_rules_effect_applies_once_however_many_conditions_it_holds`). |
| 2 | `TechnicalStrategyFactory` has no hard-coded strategy methods any more. | Done | The rule `STRATEGY-FROM-SETTINGS` of the checker `tools/architecture_check.py` (run from `backend/`) reports 0 for `src`: no module builds a `TechnicalStrategy` or `TechnicalRule`; pydantic validates them from `config/strategies/*.json` or the owner's saved rows. `tests/test_architecture_check.py::test_rule_reports_every_violation_in_its_failing_example` shows that the rule finds each planted builder. |
| 3 | The factory only turns validated configuration into typed `TechnicalCriterion` objects. | Superseded | The owner's 2026-11-03 ruling (`docs/strategy-implementation-handoff-2026-11-03.zh-TW.md`) replaced criteria classes with formulas the user composes, and ships three built-in strategies. Formulas are typed parts (`a_domain/rules/technical/formula.py`) validated as a whole (`tests/test_technical_settings_validation.py::test_an_invalid_indicator_or_formula_is_refused`). |
| 4 | Unknown criterion names are refused when the configuration loads. | Done | An unknown indicator kind, formula part, operator, output or indicator id is refused: `tests/test_technical_settings_validation.py::test_an_invalid_indicator_or_formula_is_refused` |
| 5 | Invalid criterion parameters are refused before a workflow starts. | Done | `tests/test_technical_settings_validation.py::test_an_invalid_indicator_or_formula_is_refused`, `tests/test_technical_settings_validation.py::test_each_built_in_strategy_file_is_a_valid_strategy_that_needs_61_bars` (the built-in files load with the settings at startup) |
| 6 | The UI configuration never passes Python class names or dynamic imports. | Done | Settings are data: indicator kinds, operators and fields are enum values, and nothing evaluates text (`tests/test_technical_settings_validation.py::test_an_invalid_indicator_or_formula_is_refused`). |
| 7 | Domain criteria stay typed Python classes that can be tested on their own. | Superseded | The owner's 2026-11-03 ruling (`docs/strategy-implementation-handoff-2026-11-03.zh-TW.md`) replaced criteria classes with formulas the user composes, and ships three built-in strategies. The formula parts and the indicator math are tested on their own: `tests/test_technical_formula.py`, `tests/test_technical_indicator_calculator.py`. |
| 8 | The Conservative, Moderate, Aggressive, Buzz and Nightly behavior survives the migration. | Superseded | The owner's 2026-11-03 ruling (`docs/strategy-implementation-handoff-2026-11-03.zh-TW.md`) replaced criteria classes with formulas the user composes, and ships three built-in strategies. Conservative, Balanced (was Moderate) and Aggressive score 300 seeded random stocks exactly as the criteria did: `tests/test_built_in_strategies_regression.py::test_built_in_strategies_score_every_stock_as_the_criteria_they_replaced`. Buzz and Nightly are no longer built in. |
| 9 | `strategies.yaml` stays the source of truth until the UI persistence layer exists. | Done | The persistence layer exists, so the condition has ended. The built-in strategies are `config/strategies/*.json`; each owner's settings are SQL rows (`tests/test_technical_settings_repository.py::test_a_first_load_saves_the_initial_settings_at_revision_0_and_a_later_load_never_resets_them`, `tests/test_technical_settings_repository.py::test_saving_settings_never_changes_the_built_in_strategy_files`). |
| 10 | Buzz can offer modes such as Safety Only, Loose Confirmation and Strict Confirmation. | Superseded | The owner's 2026-11-03 ruling (`docs/strategy-implementation-handoff-2026-11-03.zh-TW.md`) replaced criteria classes with formulas the user composes, and ships three built-in strategies. An owner can save any number of strategies and select one as `buzz_strategy_id` (`tests/test_technical_strategy_selection.py::test_buzz_runs_the_saved_buzz_strategy_and_every_other_workflow_the_saved_active_one`). |
| 11 | Changing the strategy composition needs no change to `Pipeline`. | Done | `tests/test_web_api.py::test_a_save_replaces_the_settings_raises_the_revision_and_drives_the_next_run`, `tests/test_technical_formula.py::test_a_new_period_under_the_same_indicator_id_changes_every_rule_that_reads_it` |

## Technical debt and enabler stories

| # | Criterion | Status | Evidence |
| --- | --- | --- | --- |
| 1 | Clean up the Yahoo Finance adapter. | Done | `tests/test_yahoo_finance_adapter.py::test_stocks_are_deduplicated_and_requested_in_batches`, `tests/test_yahoo_finance_adapter.py::test_history_returns_daily_bars_per_stock_stamped_at_their_session_close`. Commits `1c6d8b4` and `aeff21e` reduced the adapter to one batched download path behind the port methods. |
| 2 | Use one `MarketClock` name and one Taiwan time zone. | Done | `tests/test_market_clock.py::test_trading_date_is_the_taipei_calendar_date`, `tests/test_utc_datetime.py::test_every_datetime_column_of_every_table_is_a_utc_datetime`. `TaiwanMarketClock` is the only clock and `TAIWAN_TIMEZONE` the only zone (`c_infrastructure/system/market_clock.py:11`). |
| 3 | Remove the repository default for a missing `candidate_source`. | Done | `tests/test_watchlist_rule.py::test_an_entry_without_a_type_is_refused_before_the_repository_can_save_it_as_technical`, `tests/test_watchlist_rule.py::test_a_stored_row_without_a_type_fails_to_load_instead_of_reading_as_technical`. This is US-002 #4. |
| 4 | Clean up the data validation and error handling of `AiReportParser`. | Done | `tests/test_ai_report_parser.py::test_a_missing_score_is_a_parse_error_not_a_neutral_default`, `tests/test_ai_report_parser.py::test_an_unusable_ai_response_leaves_the_stock_without_ai_or_composite_score` |
| 5 | Keep the README, the CLI text, the dependency wiring, the tests and the API schema in step with every workflow change. | Partial | Untested. The README was brought in line on 2026-10-31 (commits 525644c and 2267d59, merged in fb78ec4): menu 4 analyses and offers every requested stock, `config/technical.yaml` replaces `config/strategies.yaml`, the analysis keys match `config/appsetting.yaml`, and the flow names the one `Pipeline` and the three order steps. No test keeps the README in step, so a later change can make it drift again. |

## Owner decisions

The owner decided that all user-facing text is English. Where a criterion names a Chinese label, the app shows an English label with the same meaning:

- US-102 #5 asks for 「資料不足」. The report shows `Insufficient data` with the reason (`EpsUnavailable.describe`, `a_domain/model/fundamentals/eps.py:113`, with each reason's sentence in `EpsUnavailableReason.label`, `a_domain/types/enums.py:314`).
- US-105 #7 asks for 「基於指定本益比的估值」. The report shows `Valuation based on a specified P/E` (`a_domain/rules/valuation/valuation.py:150` and `d_presentation/cli/valuation_views.py:195`).
- The EPS source 公開資訊觀測站 shows as `MOPS` (`a_domain/model/fundamentals/eps.py:54`).
- The EPS kinds 單季, 累計, 年度 and 近四季 show as `single quarter`, `cumulative`, `annual` and `TTM`, and 實際值 and 預估值 show as `actual` and `estimate` (`a_domain/types/enums.py:229-243`).

The owner also ruled on these on 2026-10-31, and the code follows each ruling:

- **Odd lots go ROD.** `ShioajiExecutionProvider` sends the board-lot part IOC and the intraday odd-lot part ROD (`ODD_LOT_TIME_IN_FORCE`, `c_infrastructure/trading/shioaji/execution_provider.py:40` and `:292`), and cancels a part still working after its polls (`tests/test_shioaji_execution_provider.py::test_an_odd_lot_rod_part_still_working_after_the_polls_is_cancelled_and_the_order_says_so`).
- **A BUY risks a share of the account's equity.** `AccountRiskCheck` fixes the run's equity once, before its first decision (`ManualSignal` for a manual BUY): cash plus each position at its latest quote, else its last daily close, else its average cost (`EquityRule`, `a_domain/rules/trading/account_value.py:46`). `SizingRule` takes `risk_per_trade_pct` of that equity and still caps each BUY by the cash the run's earlier BUYs left (`a_domain/rules/trading/sizing.py:29-52`, `tests/test_workflow_orchestration.py::test_one_runs_buys_risk_a_share_of_the_equity_best_score_first_until_the_cash_runs_out`).
- **Bond ETFs are untaxed through 2026-12-31.** `SecurityKind.BOND_ETF` is a code that starts with `00` and ends with `B` (`a_domain/types/enums.py:39`). A bond ETF SELL on or before `market.bond_etf_tax_exempt_until` pays no tax, and pays `etf_tax_rate` after it (`a_domain/rules/trading/cost.py:35`, `config/appsetting.yaml:114`, `tests/test_trading_cost.py::test_a_sell_pays_the_stock_rate_on_a_stock_the_etf_rate_on_an_etf_and_nothing_on_a_bond_etf_until_its_exemption_ends`).
- **Report prompts ask for English.** The fundamental, momentum, sentiment and valuation prompts say `Write every string in English.` (`config/instructions.yaml:25`, `:45`, `:65` and `:85`, `tests/test_report_prompts.py`). The LINE chat prompts are unchanged, because users chat there in Chinese.
- **US-005 replaces US-003 #2, and Intraday still analyses held positions that failed.** `docs/requirements.md` carries an owner note under each criterion (lines 87 and 353).

## Open decisions

These are still open. Each one cites what shows the current state.

1. **Live intraday check.** The app sends orders only in continuous trading, weekdays from 09:00 to 13:25 Taipei time (`config/appsetting.yaml:143-144`, `a_domain/rules/trading/order_rule.py:47`). No drive has filled an order yet, because every drive ran on Saturday 2026-10-31 with the market closed (`intraday.md: intraday-orders`, `buzz-scan.md: buzz-orders`). The mock broker needs no key for this drive.
2. **Shioaji against a real account.** US-301 #1 to #3 stay Partial until a run logs in to Shioaji. `environment: test` logs in to Sinopac's paper-trading environment with `SHIOAJI_API_KEY_TEST` and `SHIOAJI_SECRET_KEY_TEST`, so this needs no real money, only the owner's paper-trading keys.
3. **Odd-lot wait.** The adapter cancels a part still working after `shioaji.max_polls` (10) polls `shioaji.poll_interval_seconds` (0.5 s) apart, about 4.5 seconds (`config/appsetting.yaml:180-182`). A news report says that TWSE matches intraday odd lots every 5 seconds; nobody has checked that against TWSE's own rules. If it is true, an odd-lot ROD part can be cancelled before its first match. Should `max_polls` go up?
4. **Equity sizing spends most of the cash.** At the shipped `risk_per_trade_pct` 0.02 and `stop_loss_pct` 0.10 (`config/appsetting.yaml:48-49`), each BUY is about 20% of equity. In the six-stock Intraday test, the first four BUYs get 2,000 shares, the fifth 1,985 and the sixth HOLD, committing 999,922 of 1,000,000, where the old pace committed 738,348. Are these the risk settings the owner wants with equity sizing?
5. **A cancelled run's record under a concurrent reader.** One Web API Full Cycle stopped while another process read `stock_agent.db` logged `Run record not saved ... database is locked`, so the run kept no end time and reads as `unfinished` (`b_application/use_cases/ship/run_history.py:51-57`). Two reruns without the reader saved it. SQLite is opened with the driver's default busy timeout and journal mode (`c_infrastructure/database/db_connector.py:45`); WAL mode would let readers and the writer work at once. The cause is a guess, and the fix changes how every database is opened.
