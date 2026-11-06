CREATE TABLE account_snapshots (
	snapshot_id CHAR(32) NOT NULL, 
	taken_at DATETIME NOT NULL, 
	run_id CHAR(32) NOT NULL, 
	order_id CHAR(32) NOT NULL, 
	cash FLOAT NOT NULL, 
	positions JSON NOT NULL, 
	owner_id VARCHAR NOT NULL, 
	PRIMARY KEY (snapshot_id)
);

CREATE INDEX ix_account_snapshots_order_id ON account_snapshots (order_id);

CREATE INDEX ix_account_snapshots_owner_taken ON account_snapshots (owner_id, taken_at);

CREATE INDEX ix_account_snapshots_run_id ON account_snapshots (run_id);

CREATE INDEX ix_account_snapshots_taken_at ON account_snapshots (taken_at);

CREATE TABLE ai_call_totals (
	day DATE NOT NULL, 
	calls INTEGER NOT NULL, 
	PRIMARY KEY (day)
);

CREATE TABLE ai_calls (
	owner_id VARCHAR NOT NULL, 
	day DATE NOT NULL, 
	calls INTEGER NOT NULL, 
	PRIMARY KEY (owner_id, day)
);

CREATE TABLE article_sentiments (
	stock_id VARCHAR NOT NULL, 
	article_url VARCHAR NOT NULL, 
	label VARCHAR NOT NULL, 
	confidence FLOAT NOT NULL, 
	classified_at DATETIME NOT NULL, 
	PRIMARY KEY (stock_id, article_url)
);

CREATE TABLE mock_cash (
	owner_id VARCHAR NOT NULL, 
	current_cash FLOAT NOT NULL, 
	initial_cash FLOAT NOT NULL, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (owner_id)
);

CREATE TABLE mock_positions (
	owner_id VARCHAR NOT NULL, 
	stock_id VARCHAR NOT NULL, 
	quantity INTEGER NOT NULL, 
	average_cost FLOAT NOT NULL, 
	opened_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (owner_id, stock_id)
);

CREATE TABLE mops_quarter_eps (
	market VARCHAR NOT NULL, 
	year INTEGER NOT NULL, 
	quarter INTEGER NOT NULL, 
	fetched_at DATETIME NOT NULL, 
	cumulative_eps JSON NOT NULL, 
	PRIMARY KEY (market, year, quarter)
);

CREATE TABLE ohlcv_data (
	ts DATETIME NOT NULL, 
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
	fetched_at DATETIME NOT NULL, 
	settled_session DATE NOT NULL, 
	PRIMARY KEY (stock_id)
);

CREATE TABLE ohlcv_windows (
	stock_id VARCHAR NOT NULL, 
	first_session DATE NOT NULL, 
	PRIMARY KEY (stock_id)
);

CREATE TABLE orders (
	id CHAR(32) NOT NULL, 
	run_id CHAR(32) NOT NULL, 
	decision_id CHAR(32) NOT NULL, 
	stock_id VARCHAR NOT NULL, 
	action VARCHAR(4) NOT NULL, 
	order_type VARCHAR(6) NOT NULL, 
	quantity INTEGER NOT NULL, 
	limit_price FLOAT, 
	time_in_force VARCHAR(3) NOT NULL, 
	status VARCHAR(9) NOT NULL, 
	reason VARCHAR, 
	filled_quantity INTEGER NOT NULL, 
	average_filled_price FLOAT, 
	fee INTEGER NOT NULL, 
	tax INTEGER NOT NULL, 
	realized_pnl FLOAT, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	owner_id VARCHAR NOT NULL, 
	PRIMARY KEY (id)
);

CREATE UNIQUE INDEX ix_orders_decision_id ON orders (decision_id);

CREATE INDEX ix_orders_run_id ON orders (run_id);

CREATE INDEX ix_orders_stock_id ON orders (stock_id);

CREATE TABLE run_stock_reports (
	run_id CHAR(32) NOT NULL, 
	position INTEGER NOT NULL, 
	stock_id VARCHAR NOT NULL, 
	report JSON NOT NULL, 
	owner_id VARCHAR NOT NULL, 
	PRIMARY KEY (run_id, position)
);

CREATE TABLE schema_version (
	version INTEGER NOT NULL, 
	PRIMARY KEY (version)
);

CREATE TABLE technical_settings (
	owner_id VARCHAR NOT NULL, 
	active_strategy_id VARCHAR NOT NULL, 
	buzz_strategy_id VARCHAR NOT NULL, 
	revision INTEGER NOT NULL, 
	PRIMARY KEY (owner_id)
);

CREATE TABLE trade_signals (
	decision_id CHAR(32) NOT NULL, 
	run_id CHAR(32) NOT NULL, 
	stock_id VARCHAR NOT NULL, 
	action VARCHAR(4) NOT NULL, 
	source VARCHAR(9) NOT NULL, 
	score INTEGER NOT NULL, 
	reason VARCHAR NOT NULL, 
	quantity INTEGER NOT NULL, 
	stop_loss_price FLOAT, 
	generated_at DATETIME NOT NULL, 
	price_at_signal FLOAT NOT NULL, 
	price_observed_at DATETIME NOT NULL, 
	history_until DATETIME, 
	technical_report JSON, 
	ai_report JSON, 
	owner_id VARCHAR NOT NULL, 
	PRIMARY KEY (decision_id)
);

CREATE INDEX ix_trade_signals_run_id ON trade_signals (run_id);

CREATE INDEX ix_trade_signals_stock_id ON trade_signals (stock_id);

CREATE TABLE users (
	user_id VARCHAR NOT NULL, 
	username_sealed BLOB NOT NULL, 
	username_index BLOB NOT NULL, 
	email_sealed BLOB NOT NULL, 
	email_index BLOB NOT NULL, 
	password_hash VARCHAR NOT NULL, 
	role VARCHAR(13) NOT NULL, 
	status VARCHAR(11) NOT NULL, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (user_id), 
	UNIQUE (username_index), 
	UNIQUE (email_index)
);

CREATE TABLE watchlists (
	owner_id VARCHAR NOT NULL, 
	stock_id VARCHAR NOT NULL, 
	type VARCHAR NOT NULL, 
	created_at DATETIME NOT NULL, 
	expires_at DATETIME, 
	PRIMARY KEY (owner_id, stock_id, type)
);

CREATE INDEX ix_watchlists_expires_at ON watchlists (expires_at);

CREATE TABLE workflow_runs (
	run_id CHAR(32) NOT NULL, 
	workflow VARCHAR(15) NOT NULL, 
	execution_provider VARCHAR(7) NOT NULL, 
	order_mode VARCHAR(9) NOT NULL, 
	start_time DATETIME NOT NULL, 
	end_time DATETIME, 
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
	owner_id VARCHAR NOT NULL, 
	PRIMARY KEY (run_id)
);

CREATE INDEX ix_workflow_runs_owner_start ON workflow_runs (owner_id, start_time);

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

CREATE TABLE user_sessions (
	token_digest BLOB NOT NULL, 
	user_id VARCHAR NOT NULL, 
	created_at DATETIME NOT NULL, 
	expires_at DATETIME NOT NULL, 
	PRIMARY KEY (token_digest), 
	FOREIGN KEY(user_id) REFERENCES users (user_id)
);

CREATE INDEX ix_user_sessions_expires_at ON user_sessions (expires_at);

CREATE INDEX ix_user_sessions_user_id ON user_sessions (user_id);

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
