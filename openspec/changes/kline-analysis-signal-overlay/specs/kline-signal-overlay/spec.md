## ADDED Requirements

### Requirement: K-line chart displays signal markers
The system SHALL overlay analysis signal markers on the candlestick chart.

#### Scenario: Display BUY signal marker
- **WHEN** rendering a K-line chart with BUY signal data
- **THEN** an upward green arrow is displayed at the signal timestamp
- **AND** the arrow color is #4CAF50
- **AND** the confidence percentage is shown as a label

#### Scenario: Display SELL signal marker
- **WHEN** rendering a K-line chart with SELL signal data
- **THEN** a downward red arrow is displayed at the signal timestamp
- **AND** the arrow color is #F44336
- **AND** the confidence percentage is shown as a label

#### Scenario: Display HOLD signal marker
- **WHEN** rendering a K-line chart with HOLD signal data
- **THEN** a horizontal yellow line is displayed at the signal timestamp
- **AND** the line color is #FF9800
- **AND** the confidence percentage is shown as a label

#### Scenario: No signal data available
- **WHEN** rendering a K-line chart without analysis data
- **THEN** the chart displays only candlesticks without markers
- **AND** a caption indicates "尚无AI信号"

### Requirement: Error states are clearly displayed
The system SHALL display clear error messages when analysis fails.

#### Scenario: Analysis API returns error
- **WHEN** the analysis API returns an error response
- **THEN** a red error message is displayed below the chart
- **AND** the message includes the error detail

#### Scenario: Network error occurs
- **WHEN** a network timeout or connection error occurs
- **THEN** an error message with retry button is displayed
- **AND** clicking retry re-attempts the request
