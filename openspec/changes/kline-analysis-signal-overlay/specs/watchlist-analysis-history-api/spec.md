## ADDED Requirements

### Requirement: API returns analysis history for watchlist item
The system SHALL provide an endpoint to query analysis history for a specific watchlist item.

#### Scenario: Successfully retrieve analysis history
- **WHEN** a GET request is made to `/api/v1/watchlist/{id}/analysis-history`
- **THEN** the system returns a list of analysis records for that watchlist item
- **AND** each record contains: timestamp, signal (BUY/SELL/HOLD), confidence, price

#### Scenario: Limit analysis history results
- **WHEN** the request includes a `limit` query parameter
- **THEN** the system returns at most that many most recent records
- **AND** the default limit is 50 records

#### Scenario: Watchlist item not found
- **WHEN** the request references a non-existent watchlist ID
- **THEN** the system returns HTTP 404 with error message

#### Scenario: Watchlist item belongs to another user
- **WHEN** the request references a watchlist item not owned by current user
- **THEN** the system returns HTTP 403 Forbidden
