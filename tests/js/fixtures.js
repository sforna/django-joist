// The schema the client-side tests work on: the shape the API sends (structure
// only), small enough to reason about, with one table of each interesting kind -
// a parent, a join table, a table only reachable through a join, and a
// self-reference. `selfRef` is last so a test that forgets to sort notices.

export const authors = {
  name: 'authors',
  columns: [
    { name: 'id', type: 'bigint', nullable: false, default: null },
    { name: 'email', type: 'varchar(254)', nullable: false, default: null },
  ],
  primary_key: ['id'],
  indexes: [{ name: 'authors_email_key', columns: ['email'], unique: true }],
  foreign_keys: [],
};

export const books = {
  name: 'books',
  columns: [
    { name: 'id', type: 'bigint', nullable: false, default: null },
    { name: 'author_id', type: 'bigint', nullable: false, default: null },
    { name: 'title', type: 'varchar(255)', nullable: false, default: null },
    { name: 'price_cents', type: 'int unsigned', nullable: true, default: null },
    { name: 'status', type: "enum('draft','published')", nullable: false, default: null },
  ],
  primary_key: ['id'],
  indexes: [{ name: 'books_author_title_key', columns: ['author_id', 'title'], unique: true }],
  foreign_keys: [
    {
      name: 'books_author_id_fk',
      columns: ['author_id'],
      references_table: 'authors',
      references_columns: ['id'],
      on_update: 'no action',
      on_delete: 'cascade',
    },
  ],
};

export const tags = {
  name: 'tags',
  columns: [
    { name: 'id', type: 'bigint', nullable: false, default: null },
    { name: 'slug', type: 'varchar(50)', nullable: false, default: null },
  ],
  primary_key: ['id'],
  indexes: [],
  foreign_keys: [],
};

export const bookTags = {
  name: 'book_tags',
  columns: [
    { name: 'id', type: 'bigint', nullable: false, default: null },
    { name: 'book_id', type: 'bigint', nullable: false, default: null },
    { name: 'tag_id', type: 'bigint', nullable: false, default: null },
  ],
  primary_key: ['id'],
  indexes: [],
  foreign_keys: [
    {
      name: 'book_tags_book_id_fk',
      columns: ['book_id'],
      references_table: 'books',
      references_columns: ['id'],
      on_update: 'no action',
      on_delete: 'cascade',
    },
    {
      name: 'book_tags_tag_id_fk',
      columns: ['tag_id'],
      references_table: 'tags',
      references_columns: ['id'],
      on_update: 'no action',
      on_delete: 'cascade',
    },
  ],
};

export const selfRef = {
  name: 'folders',
  columns: [
    { name: 'id', type: 'bigint', nullable: false, default: null },
    { name: 'parent_id', type: 'bigint', nullable: true, default: null },
  ],
  primary_key: ['id'],
  indexes: [],
  foreign_keys: [
    {
      name: 'folders_parent_id_fk',
      columns: ['parent_id'],
      references_table: 'folders',
      references_columns: ['id'],
      on_update: 'no action',
      on_delete: 'no action',
    },
  ],
};

/** Every table, in a deliberate order: `folders` is not where sorting would put it. */
export const schema = [books, authors, tags, bookTags, selfRef];

export const names = (tables) => tables.map((t) => t.name);
export const sortedNames = (tables) => names(tables).sort();
