export const DEFAULT_CSV_MAPPING = Object.freeze({ category_column: 'category', amount_column: 'amount',
  delimiter: ',', decimal_separator: '.', thousands_separator: '', missing_category: 'uncategorized' });

export function validateCsvMapping(value = {}) {
  const result = { ...DEFAULT_CSV_MAPPING, ...value };
  for (const key of ['category_column', 'amount_column']) {
    if (typeof result[key] !== 'string' || !result[key].trim() || result[key].length > 200) throw new Error('Choose non-empty column names up to 200 characters.');
  }
  if (result.category_column === result.amount_column) throw new Error('Choose different columns for grouping and amount.');
  if (![',', ';', '\t', '|'].includes(result.delimiter)) throw new Error('Choose a supported CSV delimiter.');
  if (!['.', ','].includes(result.decimal_separator) || !['', ',', '.', ' '].includes(result.thousands_separator)
      || result.decimal_separator === result.thousands_separator) throw new Error('Choose different decimal and thousands separators.');
  if (!['uncategorized', 'reject'].includes(result.missing_category)) throw new Error('Choose how to handle missing categories.');
  return Object.fromEntries(Object.keys(DEFAULT_CSV_MAPPING).map(key => [key, result[key]]));
}

export function csvHeader(text, delimiter = ',') {
  const fields = [];
  let field = '', quoted = false, closed = false;
  const value = text.replace(/^\uFEFF/, '');
  for (let index = 0; index < value.length; index++) {
    const character = value[index];
    if (quoted) {
      if (character === '"') {
        if (value[index + 1] === '"') { field += '"'; index++; }
        else { quoted = false; closed = true; }
      } else field += character;
    } else if (character === '"') {
      if (field || closed) throw new Error('CSV header contains an unexpected quote.');
      quoted = true;
    } else if (character === delimiter || character === '\r' || character === '\n') {
      fields.push(field); field = ''; closed = false;
      if (character !== delimiter) return checkHeaders(fields);
    } else {
      if (closed) throw new Error('CSV header has text after a closing quote.');
      field += character;
    }
  }
  if (quoted) throw new Error('CSV header is incomplete or exceeds 64 KiB.');
  fields.push(field);
  return checkHeaders(fields);
}

function checkHeaders(fields) {
  if (fields.length > 200 || fields.some(field => !field || field.length > 200) || new Set(fields).size !== fields.length) {
    throw new Error('CSV needs 1–200 unique, non-empty column names, up to 200 characters each.');
  }
  return fields;
}

export async function inspectCsv(file, delimiter = ',') {
  return csvHeader(await file.slice(0, 65536).text(), delimiter);
}
