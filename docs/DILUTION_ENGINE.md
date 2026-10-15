# Dilution Engine Documentation

## Overview

The Dilution Engine analyzes SEC filings and corporate actions to detect dilution risks. This is one of the most critical modules for penny stock analysis.

## Detected Events

### Offerings
- **Public Offering (S-1, S-3, 424B)**: New shares offered to public
- **Registered Direct**: Shares sold directly to investors
- **Private Placement (424B2, 424B7)**: Shares sold privately
- **ATM (At-The-Market)**: Ongoing share sales program
- **Shelf Registration**: Pre-registered shares available for sale
- **Equity Line**: Credit facility converting to equity

### Warrants
- **Warrant Exercise**: Existing warrants being exercised
- **Warrant Overhang**: Potential dilution from warrants outstanding

### Convertible Debt
- **Convertible Notes**: Debt convertible to equity
- **Convertible Debt**: Debt instruments with conversion features

### Corporate Actions
- **Reverse Split**: Share consolidation
- **Share Issuance**: Direct share issuance

## Filing Types Monitored

- S-1, S-3, S-4, F-1, F-3, F-4
- 424B, 424B1, 424B2, 424B3, 424B4, 424B5, 424B7, 424B8
- 8-K (for material events)
- 10-K, 10-Q
- Form 4, 13D, 13G, 144
- DEF 14A

## Confidence Levels

- **High**: Clear filing language, confirmed numbers
- **Medium**: Inferred from filing context
- **Low**: Ambiguous language, unconfirmed data

## Share Outstanding Tracking

Maintains historical share outstanding data and calculates:
- `shares_outstanding_change_30d`
- `shares_outstanding_change_90d`
- `shares_outstanding_change_180d`
- `shares_outstanding_change_1y`

## Risk Flags

The engine generates:
- `RECENT_OFFERING`
- `ACTIVE_ATM`
- `SHELF_REGISTRATION`
- `WARRANT_OVERHANG`
- `CONVERTIBLE_DEBT`
- `SHARE_DILUTION`

## No Hallucination

The engine never invents financial data. If information cannot be extracted from filings, it returns `null` with low confidence.

## Source Priority

1. SEC EDGAR filings (primary)
2. Company press releases
3. Financial news sources
4. Data aggregators