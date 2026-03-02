package api

// ListNamespaces lists available namespaces.
func (c *Client) ListNamespaces() (*NamespaceListResponse, error) {
	url := c.apiURL("/namespaces")
	req, err := c.newRequest("GET", url, nil)
	if err != nil {
		return nil, err
	}
	var resp NamespaceListResponse
	if err := c.do(req, &resp); err != nil {
		return nil, err
	}
	return &resp, nil
}
