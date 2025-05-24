create table if not exists prices (
	id integer primary key autoincrement,
	timestamp text not null,
	price real not null
)