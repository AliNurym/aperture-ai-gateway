const paths = {
  grid: "M3 3h7v7H3z M14 3h7v7h-7z M3 14h7v7H3z M14 14h7v7h-7z",
  code: "m8 7-5 5 5 5m8-10 5 5-5 5m-3-13-2 16",
  network: "M9 3h6v6H9z M2 15h6v6H2z M16 15h6v6h-6z M12 9v3H5v3m7-3h7v3",
  book: "M12 5C8 2 4 3 2 4v16c3-2 7-2 10 0 3-2 7-2 10 0V4c-3-2-7-2-10 1v15",
  arrow: "M4 12h16m-6-6 6 6-6 6",
  chevron: "m6 9 6 6 6-6",
  play: "m8 4 12 8-12 8Z",
  stop: "M5 5h14v14H5z",
  check: "m5 12 4 4L19 6",
  refresh: "M20 7v5h-5M4 17v-5h5m11-1a8 8 0 0 0-14-5m-2 7a8 8 0 0 0 14 5",
  clock: "M12 8v5l3 2 M22 12a10 10 0 1 1-20 0 10 10 0 0 1 20 0",
  chip: "M6 6h12v12H6z M9 1v5m6-5v5M9 18v5m6-5v5M1 9h5m-5 6h5m12-6h5m-5 6h5 M9 9h6v6H9z",
  shield: "m12 2 9 4v6c0 5-9 10-9 10S3 17 3 12V6Z m-5 10 3 3 5-6",
  download: "M12 3v12m-5-5 5 5 5-5M4 16v5h16v-5",
  eye: "M2 12s3-7 10-7 10 7 10 7-3 7-10 7-10-7-10-7Z M15 12a3 3 0 1 1-6 0 3 3 0 0 1 6 0",
  upload: "M12 16V4m-5 5 5-5 5 5M4 16v5h16v-5",
  copy: "M8 8h13v13H8z M16 8V3H3v13h5",
  close: "m6 6 12 12M6 18 18 6",
  spark: "m12 2 3 7 7 3-7 3-3 7-3-7-7-3 7-3Z",
  wallet: "M3 5h16v4H3V5Zm0 4v11h18V9H3Zm14 5h4",
  external: "M14 3h7v7m0-7L10 14M10 3H3v18h18v-7",
};

export default function Icon({ name, size = 20, spinning = false, ...props }) {
  const icon = (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.7"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      data-icon={name}
      {...props}
    >
      <path d={paths[name] || paths.spark} />
    </svg>
  );
  return spinning ? <span className="motion-icon-spin" aria-hidden="true">{icon}</span> : icon;
}
