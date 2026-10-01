export function saveFile(name, contents, type = 'text/plain') {
  const url = URL.createObjectURL(new Blob([contents], { type }));
  const link = document.createElement('a');
  link.href = url; link.download = name; link.hidden = true;
  document.body.append(link);
  try { link.click(); }
  finally {
    link.remove();
    // Give browsers that route saving through their host time to consume the URL.
    setTimeout(() => URL.revokeObjectURL(url), 60000);
  }
}
