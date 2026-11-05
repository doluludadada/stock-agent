CREATE TYPE workflow AS ENUM ('FULL_CYCLE', 'BUZZ_SCAN', 'INTRADAY', 'SPECIFIC_STOCKS', 'MANUAL_BUY', 'VALUATION', 'RESEARCH');

CREATE TYPE executionprovider AS ENUM ('MOCK', 'SHIOAJI');

CREATE TYPE ordermode AS ENUM ('MOCK_ONLY', 'LIVE', 'DISABLED');

CREATE TYPE tradeaction AS ENUM ('BUY', 'SELL', 'HOLD');

CREATE TYPE signalsource AS ENUM ('COMBINED', 'STOP_LOSS', 'MANUAL');

CREATE TYPE ordertype AS ENUM ('MARKET', 'LIMIT');

CREATE TYPE timeinforce AS ENUM ('ROD', 'IOC', 'FOK');

CREATE TYPE orderstatus AS ENUM ('PENDING', 'SUBMITTED', 'FILLED', 'CANCELLED', 'FAILED', 'REJECTED');

CREATE TABLE schema_version (
	version SERIAL NOT NULL, 
	PRIMARY KEY (version)
);

CREATE TABLE article_sentiments (
	stock_id VARCHAR NOT NULL, 
	article_url VARCHAR NOT NULL, 
	label VARCHAR NOT NULL, 
	confidence FLOAT NOT NULL, 
	classified_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	PRIMARY KEY (stock_id, article_url)
);

CREATE TABLE workflow_runs (
	run_id UUID NOT NULL, 
	workflow workflow NOT NULL, 
	execution_provider executionprovider NOT NULL, 
	order_mode ordermode NOT NULL, 
	start_time TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	end_time TIMESTAMP WITHOUT TIME ZONE, 
	technical_strategy_id VARCHAR, 
	ai_model VARCHAR, 
	total_scanned INTEGER NOT NULL, 
	buzz_scanned INTEGER NOT NULL, 
	buzz_qualified INTEGER NOT NULL, 
	sentiment_analysed INTEGER NOT NULL, 
	passed_technical INTEGER NOT NULL, 
	ai_analysed INTEGER NOT NULL, 
	signals_generated INTEGER NOT NULL, 
	orders_submitted INTEGER NOT NULL, 
	orders_filled INTEGER NOT NULL, 
	orders_refused INTEGER NOT NULL, 
	stale_market_data_count INTEGER NOT NULL, 
	errors JSON NOT NULL, 
	execution_log JSON NOT NULL, 
	failure VARCHAR, 
	PRIMARY KEY (run_id)
);

CREATE TABLE trade_signals (
	decision_id UUID NOT NULL, 
	run_id UUID NOT NULL, 
	stock_id VARCHAR NOT NULL, 
	action tradeaction NOT NULL, 
	source signalsource NOT NULL, 
	score INTEGER NOT NULL, 
	reason VARCHAR NOT NULL, 
	quantity INTEGER NOT NULL, 
	stop_loss_price FLOAT, 
	generated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	price_at_signal FLOAT NOT NULL, 
	price_observed_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	history_until TIMESTAMP WITHOUT TIME ZONE, 
	technical_report JSON, 
	ai_report JSON, 
	PRIMARY KEY (decision_id)
);

CREATE INDEX ix_trade_signals_run_id ON trade_signals (run_id);

CREATE INDEX ix_trade_signals_stock_id ON trade_signals (stock_id);

CREATE TABLE orders (
	id UUID NOT NULL, 
	run_id UUID NOT NULL, 
	decision_id UUID NOT NULL, 
	stock_id VARCHAR NOT NULL, 
	action tradeaction NOT NULL, 
	order_type ordertype NOT NULL, 
	quantity INTEGER NOT NULL, 
	limit_price FLOAT, 
	time_in_force timeinforce NOT NULL, 
	status orderstatus NOT NULL, 
	reason VARCHAR, 
	filled_quantity INTEGER NOT NULL, 
	average_filled_price FLOAT, 
	fee INTEGER NOT NULL, 
	tax INTEGER NOT NULL, 
	realized_pnl FLOAT, 
	created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	PRIMARY KEY (id)
);

CREATE UNIQUE INDEX ix_orders_decision_id ON orders (decision_id);

CREATE INDEX ix_orders_run_id ON orders (run_id);

CREATE INDEX ix_orders_stock_id ON orders (stock_id);

CREATE TABLE account_snapshots (
	snapshot_id UUID NOT NULL, 
	taken_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	run_id UUID NOT NULL, 
	order_id UUID NOT NULL, 
	cash FLOAT NOT NULL, 
	positions JSON NOT NULL, 
	PRIMARY KEY (snapshot_id)
);

CREATE INDEX ix_account_snapshots_run_id ON account_snapshots (run_id);

CREATE INDEX ix_account_snapshots_taken_at ON account_snapshots (taken_at);

CREATE INDEX ix_account_snapshots_order_id ON account_snapshots (order_id);

CREATE TABLE run_stock_reports (
	run_id UUID NOT NULL, 
	position INTEGER NOT NULL, 
	stock_id VARCHAR NOT NULL, 
	report JSON NOT NULL, 
	PRIMARY KEY (run_id, position)
);

CREATE TABLE watchlists (
	stock_id VARCHAR NOT NULL, 
	type VARCHAR NOT NULL, 
	created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	expires_at TIMESTAMP WITHOUT TIME ZONE, 
	PRIMARY KEY (stock_id, type)
);

CREATE INDEX ix_watchlists_expires_at ON watchlists (expires_at);

CREATE TABLE ohlcv_data (
	ts TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	open FLOAT NOT NULL, 
	high FLOAT NOT NULL, 
	low FLOAT NOT NULL, 
	close FLOAT NOT NULL, 
	volume INTEGER NOT NULL, 
	adj_close FLOAT, 
	stock_id VARCHAR NOT NULL, 
	PRIMARY KEY (ts, stock_id)
);

CREATE TABLE ohlcv_fetches (
	stock_id VARCHAR NOT NULL, 
	fetched_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	settled_session DATE NOT NULL, 
	PRIMARY KEY (stock_id)
);

CREATE TABLE ohlcv_windows (
	stock_id VARCHAR NOT NULL, 
	first_session DATE NOT NULL, 
	PRIMARY KEY (stock_id)
);

CREATE TABLE mops_quarter_eps (
	market VARCHAR NOT NULL, 
	year INTEGER NOT NULL, 
	quarter INTEGER NOT NULL, 
	fetched_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	cumulative_eps JSON NOT NULL, 
	PRIMARY KEY (market, year, quarter)
);

CREATE TABLE technical_settings (
	owner_id VARCHAR NOT NULL, 
	active_strategy_id VARCHAR NOT NULL, 
	buzz_strategy_id VARCHAR NOT NULL, 
	revision INTEGER NOT NULL, 
	PRIMARY KEY (owner_id)
);

CREATE TABLE mock_cash (
	account_id VARCHAR NOT NULL, 
	current_cash FLOAT NOT NULL, 
	initial_cash FLOAT NOT NULL, 
	created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	PRIMARY KEY (account_id)
);

CREATE TABLE mock_positions (
	account_id VARCHAR NOT NULL, 
	stock_id VARCHAR NOT NULL, 
	quantity INTEGER NOT NULL, 
	average_cost FLOAT NOT NULL, 
	opened_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	PRIMARY KEY (account_id, stock_id)
);

CREATE TABLE technical_strategies (
	owner_id VARCHAR NOT NULL, 
	strategy_id VARCHAR NOT NULL, 
	position INTEGER NOT NULL, 
	name VARCHAR NOT NULL, 
	base_score INTEGER NOT NULL, 
	block_failure_penalty INTEGER NOT NULL, 
	failure_score_reduction INTEGER NOT NULL, 
	pass_score_increase INTEGER NOT NULL, 
	PRIMARY KEY (owner_id, strategy_id), 
	FOREIGN KEY(owner_id) REFERENCES technical_settings (owner_id) ON DELETE CASCADE
);

CREATE TABLE technical_indicators (
	owner_id VARCHAR NOT NULL, 
	strategy_id VARCHAR NOT NULL, 
	indicator_id VARCHAR NOT NULL, 
	kind VARCHAR NOT NULL, 
	period INTEGER, 
	fast INTEGER, 
	slow INTEGER, 
	signal INTEGER, 
	std FLOAT, 
	k_period INTEGER, 
	d_period INTEGER, 
	PRIMARY KEY (owner_id, strategy_id, indicator_id), 
	FOREIGN KEY(owner_id, strategy_id) REFERENCES technical_strategies (owner_id, strategy_id) ON DELETE CASCADE
);

CREATE TABLE technical_rules (
	owner_id VARCHAR NOT NULL, 
	strategy_id VARCHAR NOT NULL, 
	position INTEGER NOT NULL, 
	name VARCHAR NOT NULL, 
	effect VARCHAR NOT NULL, 
	PRIMARY KEY (owner_id, strategy_id, position), 
	FOREIGN KEY(owner_id, strategy_id) REFERENCES technical_strategies (owner_id, strategy_id) ON DELETE CASCADE
);

CREATE TABLE technical_formula_nodes (
	owner_id VARCHAR NOT NULL, 
	strategy_id VARCHAR NOT NULL, 
	rule_position INTEGER NOT NULL, 
	position INTEGER NOT NULL, 
	parent_position INTEGER, 
	node VARCHAR NOT NULL, 
	operator VARCHAR, 
	constant FLOAT, 
	field VARCHAR, 
	indicator_id VARCHAR, 
	output VARCHAR, 
	bars_ago INTEGER, 
	PRIMARY KEY (owner_id, strategy_id, rule_position, position), 
	FOREIGN KEY(owner_id, strategy_id, rule_position) REFERENCES technical_rules (owner_id, strategy_id, position) ON DELETE CASCADE, 
	FOREIGN KEY(owner_id, strategy_id, rule_position, parent_position) REFERENCES technical_formula_nodes (owner_id, strategy_id, rule_position, position) ON DELETE CASCADE, 
	FOREIGN KEY(owner_id, strategy_id, indicator_id) REFERENCES technical_indicators (owner_id, strategy_id, indicator_id), 
	CONSTRAINT one_root CHECK ((position = 0) = (parent_position IS NULL))
);
