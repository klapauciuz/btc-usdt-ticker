create table if not exists prices (
	id integer primary key autoincrement,
	timestamp text not null,
	price real not null,
	open real,
	high real,
	low real,
	close real,
	volume real,
	marketcap real
);