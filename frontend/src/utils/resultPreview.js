export const MAX_PREVIEW_BYTES = 1024 * 1024;
const MAX_ROWS = 100;
const MAX_COLUMNS = 32;
const MAX_TEXT = 12000;

export function canPreviewFile(file) {
  return Number.isSafeInteger(file?.size_bytes) && file.size_bytes <= MAX_PREVIEW_BYTES
    && /\.(json|csv|txt|log)$/i.test(file.name);
}

function cell(value) {
  const text = value == null ? '' : typeof value === 'object' ? JSON.stringify(value) : String(value);
  return text.length > 512 ? text.slice(0, 512) + '…' : text;
}

function csvPreview(text) {
  const rows = [];
  let row = [], value = '', quoted = false, closed = false, rowCount = 0;
  const field = () => {
    if (row.length >= MAX_COLUMNS) throw new Error('This CSV has more than 32 columns.');
    row.push(value); value = ''; closed = false;
  };
  const endRow = () => {
    field();
    if (rows.length <= MAX_ROWS) rows.push(row.map(cell));
    rowCount += 1; row = [];
  };
  for (let index = 0; index < text.length; index += 1) {
    const char = text[index];
    if (quoted) {
      if (char === '"' && text[index + 1] === '"') { value += '"'; index += 1; }
      else if (char === '"') { quoted = false; closed = true; }
      else value += char;
    } else if (char === ',') field();
    else if (char === '\r' || char === '\n') {
      // Match the CSV job reader: ignore empty physical lines, while retaining
      // quoted empty fields and records containing explicit delimiters.
      if (value || row.length || closed) endRow();
      if (char === '\r' && text[index + 1] === '\n') index += 1;
    } else if (char === '"' && !value && !closed) quoted = true;
    else {
      if (closed || char === '"') throw new Error('CSV quoting is invalid.');
      value += char;
    }
  }
  if (quoted) throw new Error('CSV contains an unfinished quoted field.');
  if (value || row.length || closed) endRow();
  if (!rows.length) return { type: 'text', text: '', truncated: false };
  const columns = rows.shift();
  if (rows.some(item => item.length !== columns.length)) throw new Error('CSV rows have different column counts.');
  return { type: 'table', columns, rows, count: Math.max(0, rowCount - 1) };
}

function jsonPreview(text) {
  const value = JSON.parse(text);
  if (value && !Array.isArray(value) && Number.isSafeInteger(value.valid_rows) && value.valid_rows >= 0
      && Number.isSafeInteger(value.invalid_rows) && value.invalid_rows >= 0
      && value.groups && typeof value.groups === 'object' && !Array.isArray(value.groups)) {
    const entries = Object.entries(value.groups);
    if (entries.every(([, group]) => group && Number.isSafeInteger(group.rows) && group.rows > 0
        && typeof group.total === 'number' && Number.isFinite(group.total))) {
      const quality = value.quality && typeof value.quality === 'object' ? value.quality : null;
      const reasons = quality?.invalid_reasons && typeof quality.invalid_reasons === 'object'
        ? Object.entries(quality.invalid_reasons).filter(([, count]) => Number.isSafeInteger(count) && count >= 0).slice(0, 20) : [];
      return { type: 'report', metrics: [
        ['Accepted rows', value.valid_rows], ['Skipped rows', value.invalid_rows], ['Categories', entries.length],
      ], quality: quality ? { reasons, missingGroups: Number.isSafeInteger(quality.missing_category_rows) ? quality.missing_category_rows : 0,
        duplicatesChecked: quality.duplicate_check !== 'not_performed' } : null,
      columns: ['Category', 'Rows', 'Total', 'Average'], count: entries.length,
      rows: entries.slice(0, MAX_ROWS).map(([category, group]) => [cell(category), group.rows.toLocaleString('en-US'),
        typeof group.total_decimal === 'string' && group.total_decimal.length < 80 ? cell(group.total_decimal) : group.total.toLocaleString('en-US', { maximumFractionDigits: 4 }),
        (group.total / group.rows).toLocaleString('en-US', { maximumFractionDigits: 4 })]) };
    }
  }
  if (Array.isArray(value) && value.length && value.slice(0, MAX_ROWS).every(item => item && typeof item === 'object' && !Array.isArray(item))) {
    const columns = [...new Set(value.slice(0, MAX_ROWS).flatMap(item => Object.keys(item)))];
    if (columns.length > 0 && columns.length <= MAX_COLUMNS) {
      return { type: 'table', columns, count: value.length,
        rows: value.slice(0, MAX_ROWS).map(item => columns.map(key => cell(item[key]))) };
    }
  }
  // Keep deeply nested or large JSON in its original text form; never recursively render it.
  return { type: 'text', text: text.slice(0, MAX_TEXT), truncated: text.length > MAX_TEXT };
}

export function previewResult(file, bytes) {
  if (!canPreviewFile(file) || bytes.byteLength > MAX_PREVIEW_BYTES) throw new Error('Preview supports JSON, CSV and text files up to 1 MiB. Download this file to open it.');
  const text = new TextDecoder('utf-8', { fatal: true }).decode(bytes).replace(/^\uFEFF/, '');
  try {
    if (/\.json$/i.test(file.name)) return jsonPreview(text);
    if (/\.csv$/i.test(file.name)) return csvPreview(text);
  } catch (error) {
    return { type: 'text', text: text.slice(0, MAX_TEXT), truncated: text.length > MAX_TEXT,
      note: 'Structured preview is unavailable: ' + error.message + ' The verified text is shown below.' };
  }
  return { type: 'text', text: text.slice(0, MAX_TEXT), truncated: text.length > MAX_TEXT };
}
