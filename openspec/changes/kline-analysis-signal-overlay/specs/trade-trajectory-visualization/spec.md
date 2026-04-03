## ADDED Requirements

### Requirement: Connect consecutive trade signals with lines
The system SHALL draw connecting lines between consecutive BUY/SELL signals to visualize trade trajectory.

#### Scenario: Connect BUY to SELL (profitable trade)
- **WHEN** a BUY signal is followed by a SELL signal at a higher price
- **THEN** a green solid line connects the two signal points
- **AND** the line color is #4CAF50

#### Scenario: Connect BUY to SELL (loss trade)
- **WHEN** a BUY signal is followed by a SELL signal at a lower price
- **THEN** a red dashed line connects the two signal points
- **AND** the line color is #F44336
- **AND** the line style is dash

#### Scenario: Connect SELL to BUY (profitable short)
- **WHEN** a SELL signal is followed by a BUY signal at a lower price
- **THEN** a green solid line connects the two signal points
- **AND** the line color is #4CAF50

#### Scenario: Connect SELL to BUY (loss short)
- **WHEN** a SELL signal is followed by a BUY signal at a higher price
- **THEN** a red dashed line connects the two signal points
- **AND** the line color is #F44336
- **AND** the line style is dash

#### Scenario: HOLD signals do not connect
- **WHEN** consecutive HOLD signals exist
- **THEN** no connecting lines are drawn between them
- **AND** each HOLD signal is displayed as an independent marker

#### Scenario: Signal sequence starts with SELL
- **WHEN** the first signal in history is SELL
- **THEN** it is displayed as a marker without incoming connection
- **AND** the trajectory starts from this point

### Requirement: Trade trajectory is interactive
The system SHALL allow users to interact with the trajectory visualization.

#### Scenario: Hover shows trade details
- **WHEN** user hovers over a connecting line
- **THEN** a tooltip displays: entry price, exit price, P&L percentage

#### Scenario: Click signal to view analysis
- **WHEN** user clicks on a signal marker
- **THEN** the analysis detail panel scrolls into view
- **AND** the corresponding analysis record is highlighted
