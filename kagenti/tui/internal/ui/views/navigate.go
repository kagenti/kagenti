package views

// NavigateMsg is sent by sub-views to navigate to a different view.
type NavigateMsg struct {
	Target string // "home", "agent-detail", "tool-detail"
	Name   string // resource name (if applicable)
}
