import Icon from "./Icon";
import { useClipboardFeedback } from "../hooks/useClipboardFeedback";

export default function CommandBlock({ label, command, children }) {
  const { status, copy } = useClipboardFeedback(command, 2400);
  const feedback = status === 'copied' ? 'Copied'
    : status === 'unavailable' ? 'Select and copy the command.' : '';

  return (
    <div className="console-command">
      <div className="console-command-heading">
        <span>{label}</span>
        <button className="console-icon-button" onClick={copy} data-copied={feedback === "Copied"} aria-label={feedback === "Copied" ? label + " command copied" : "Copy " + label.toLowerCase() + " command"} title="Copy command">
          <Icon name={feedback === "Copied" ? "check" : "copy"} size={17} />
        </button>
      </div>
      <code>{command}</code>
      {children}
      <span className="console-command-feedback" role="status">{feedback}</span>
    </div>
  );
}
