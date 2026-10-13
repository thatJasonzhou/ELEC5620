# Project context

## Product

The One-Person AI Event Management Company supports a single business owner with four AI-assisted agents. Customers request and approve events; vendors provide services; agents plan, procure, manage finances, coordinate operations, and close events.

## Actors

- Customer
- Vendor
- Business Owner
- Event Planner Agent
- Vendor Procurement Manager Agent
- Financial Manager Agent
- Event Operations Manager Agent

## Use cases

| ID | Name | Primary module |
|---|---|---|
| UC1 | Define Event Requirements | Event Planning |
| UC2 | Generate Event Proposal | Event Planning |
| UC3 | Procure Event Vendors | Vendor Procurement |
| UC4 | Prepare Event Budget and Customer Quotation | Financial Management |
| UC5 | Finalize Event Proposal | Event Planning |
| UC6 | Confirm Event Booking | Event Planning |
| UC7 | Confirm Vendor Bookings | Vendor Procurement |
| UC8 | Manage Customer Payments | Financial Management |
| UC9 | Plan and Coordinate Event Operations | Event Operations |
| UC10 | Manage Event Changes | Change and Exception |
| UC11 | Manage Event Execution | Event Operations |
| UC12 | Handle Operational Exceptions | Event Operations |
| UC13 | Manage Vendor Payments | Financial Management |
| UC14 | Handle Customer Feedback and Complaints | Feedback and Closure |
| UC15 | Verify and Close Event | Feedback and Closure |

## Stage 2 implementation rule

Every Use Case has a visible entry or status. The core flow is fully runnable, while secondary behaviors may be simplified. Each major module demonstrates at least one exception path. The UI exposes agent perception, decision, action, and result.

