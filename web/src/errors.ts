// Appendix F's Voice section gives exact copy for the known rejections —
// the raw {error, message} from the API is a technical detail, not what
// an employee should read. Unknown codes fall back to the server's own
// message rather than inventing copy for a case the plan didn't specify.
export function describeSaveError(code: string, rawMessage: string, weekday: string): string {
  switch (code) {
    case "daily_cap_exceeded":
      // The plan's own example names a specific number ("over 10 hours"),
      // but the real cap isn't exposed to the client (server is the sole
      // authority on it) — phrased generically rather than guessing it.
      return `That would put ${weekday} over your daily limit. Reduce the entry, or ask ops to raise your daily limit.`;
    case "period_locked":
      return "That date is approved and closed. Ask your approver to change anything in it.";
    case "invalid_increment":
      return "Hours must be a positive multiple of a quarter hour.";
    case "task_required":
      return "Choose a task for this entry.";
    case "task_not_open":
      return "That task is closed. Choose another task.";
    case "task_not_in_project":
      return "That task doesn't belong to this project. Choose another task.";
    case "project_not_held":
      return "You aren't assigned to that project.";
    case "billing_set_by_approver":
      // Decision 0011: said plainly, without explaining what "billing" is.
      return "The approver has set how this line is billed. Ask them to move it.";
    default:
      return rawMessage;
  }
}
