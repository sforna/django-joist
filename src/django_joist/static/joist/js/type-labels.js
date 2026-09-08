// Best-effort native-type -> Django-flavoured short label. This is a
// presentation convenience only: it is lossy and never written back into the
// schema. The native full type remains the source of truth (see the reference
// implementation's docs/DESIGN.md). The UI toggles between the two; this
// computes the "django" side, naming the closest Django model field family.

const BASE = (type) => String(type).trim().toLowerCase().match(/^[a-z0-9_]+/)?.[0] ?? '';

/**
 * @param {string} nativeType e.g. "bigint unsigned", "varchar(255)", "tinyint(1)"
 * @returns {string} e.g. "big integer field", "char field", "boolean field"
 */
export function toShortLabel(nativeType) {
  const raw = String(nativeType).trim().toLowerCase();
  const base = BASE(raw);

  // tinyint(1) is the classic boolean storage; wider tinyint is a plain int.
  if (base === 'tinyint') {
    return /\(\s*1\s*\)/.test(raw) ? 'boolean field' : 'small integer field';
  }

  switch (base) {
    case 'bigint':
    case 'int8':
      return 'big integer field';

    case 'smallint':
    case 'int2':
      return 'small integer field';

    case 'mediumint':
    case 'int':
    case 'integer':
    case 'int4':
      return 'integer field';

    case 'char':
    case 'varchar':
    case 'nvarchar':
    case 'character':
    case 'string':
      return 'char field';

    case 'text':
    case 'tinytext':
    case 'mediumtext':
    case 'longtext':
      return 'text field';

    case 'decimal':
    case 'numeric':
      return 'decimal field';

    case 'float':
    case 'float4':
    case 'double':
    case 'double precision':
    case 'real':
    case 'float8':
      return 'float field';

    case 'timestamp':
    case 'timestamptz':
    case 'datetime':
      return 'datetime field';

    case 'date':
      return 'date field';

    case 'time':
      return 'time field';

    case 'bool':
    case 'boolean':
      return 'boolean field';

    case 'json':
    case 'jsonb':
      return 'json field';

    case 'uuid':
      return 'uuid field';

    case 'binary':
    case 'varbinary':
    case 'blob':
    case 'tinyblob':
    case 'mediumblob':
    case 'longblob':
    case 'bytea':
      return 'binary field';

    // enum/set stay the keyword: the value list is shown in its own popover.
    case 'enum':
    case 'set':
      return base;

    default:
      return base;
  }
}
