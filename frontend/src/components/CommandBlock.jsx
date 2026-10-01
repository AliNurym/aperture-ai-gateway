import { useEffect, useState } from "react";
import Icon from "./Icon";

export default function CommandBlock({ label, command, children }) {
  const [feedback, setFeedback] = useState("");

  useEffect(() => {
    if (!feedback) return undefined;
    const timer = setTimeout(() => setFeedback(""), 2400);
    return () => clearTimeout(timer);
  }, [feedback]);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(command);
      setFeedback("Copied");
    } catch {
      setFeedback("Select and copy the command.");
    }
  };

  return (
    <div className="console-command">
      <div className="console-command-heading">
        <span>{label}</span>
        <button className="console-icon-button" onClick={copy} aria-label={feedback === "Copied" ? label + " command copied" : "Copy " + label.toLowerCase() + " command"} title="Copy command">
          <Icon name={feedback === "Copied" ? "check" : "copy"} size={17} />
        </button>
      </div>
      <code>{command}</code>
      {children}
      <span className="console-command-feedback" role="status">{feedback}</span>
    </div>
  );
}
