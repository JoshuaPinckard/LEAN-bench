# O1 fair-reading sets

These sets apply only to the eligible variants. They enumerate concrete conventions that a competent implementation could reasonably adopt after the designated atom is deleted. They are review and coding aids, not answer keys.

## O1e1 — strike-selection convention

- Lowest strike at or above 101% of spot — Restores the donor convention and is a common deterministic definition of approximately 1% OTM.
- Strike nearest to 101% of spot — A developer may interpret the desired moneyness as a target and minimize absolute strike distance.
- Nearest out-of-the-money strike — A common default for a directional long option when no numerical moneyness target is supplied.
- At-the-money strike nearest to spot — A standard liquid-contract default that avoids inventing an OTM percentage.
- Delta-targeted strike, such as the call nearest 0.40 delta — A practitioner may use delta as the economically meaningful strike selector.

This void is broad but not effectively unbounded: the principal implementation families are moneyness-, nearest-strike-, and delta-based selection.

## O1e2 — expiry/DTE convention

- Nearest expiration at least 7 calendar days away — Restores the donor convention and limits very short-dated gamma and expiry-processing risk.
- Nearest available expiration — A literal minimal-expiry choice is natural when the strategy is described as short-dated.
- Nearest expiration at least 1 calendar day away — This avoids same-day expiration while retaining a strongly short-dated design.
- Nearest expiration at least 5 trading days away — A developer may translate “about one week” into exchange sessions.
- Expiration nearest 30 calendar DTE — Thirty-day contracts are a common standardized choice for directional option strategies.

This void is broad but not effectively unbounded: implementations usually choose the nearest expiry, impose a minimum DTE, or target a conventional DTE.

## O1e3 — option-type convention

- Call — The bullish moving-average crossover naturally maps to positive-delta call exposure and restores the donor.
- Put — A developer could interpret the signal contrarily or use a long put as the requested option instrument despite the bullish label.

The logical reading set is bounded to the two ordinary option rights. Multi-leg structures are not fair readings because the remaining prompt requires one long option contract.

## O1e4 — position-size convention

- 1 contract — The smallest nonzero position is the safest deterministic default and restores the donor.
- Fixed number greater than one, such as 10 contracts — A developer may use a simple constant lot size for the $100,000 account.
- One contract per entry with an explicit maximum-risk check — A cautious implementation may retain unit sizing unless its premium exceeds a risk budget.
- Portfolio-percentage sizing, such as premium equal to at most 1% of equity — Risk-based sizing is a standard alternative to a fixed contract count.
- Buying-power-based sizing, such as a fixed fraction of available cash — LEAN implementations often derive quantity from current portfolio capacity.

This void is broad but not effectively unbounded for coding purposes if the coder groups fixed-unit, risk-budget, portfolio-fraction, and buying-power conventions.

## O1e5 — exit-threshold convention

- 50% gain over filled premium — Restores the donor and is a common round-number profit target for long options.
- 25% gain over filled premium — A tighter target reduces exposure to theta decay and signal reversal.
- 100% gain over filled premium — Letting the premium double is a recognizable long-option payoff convention.
- Exit when the option midpoint merely exceeds the entry price — A break-even-or-better interpretation minimizes the duration of the trade.
- No profit target; use only the specified time stop — A developer may avoid inventing a numerical threshold and retain the independently specified exit.

This void is broad but not effectively unbounded: outputs can be coded as a stated percentage/multiple, break-even, or time-stop-only.

## O1e6 — assignment/exercise handling

- Immediately market-liquidate any resulting SPY shares — Restores the donor and returns the portfolio to the strategy’s option-only state.
- Retain resulting SPY shares — A developer may accept exercise as the intended conversion of an in-the-money long call.
- Prevent exercise by liquidating the option before the exercise cutoff — A proactive implementation may make the exceptional equity state unreachable.
- Submit a do-not-exercise instruction when supported — A developer may explicitly suppress exercise rather than manage resulting shares.
- Liquidate resulting shares at the next regular-session open — This handles an exercise event reported outside liquid equity-market hours without assuming an immediate fill.

This void is not effectively unbounded, but the owner should confirm whether proactive prevention and post-event share handling belong in the same coding category.

## O1e7 — no-match handling

- Skip the signal and wait for a new crossover — Restores the donor, avoids stale intent, and never crashes.
- Skip the current Slice but retry the same signal on the next Slice — A developer may treat missing chain data as transient.
- Choose the nearest available contract under a relaxed strike rule — A developer may preserve the entry by falling back to the closest strike.
- Choose the nearest available expiration under a relaxed DTE rule — A developer may preserve the entry when the desired expiry is absent.
- Log the condition and terminate or raise an error — A strict implementation may treat an empty candidate set as invalid data rather than a normal skip.

This void is broad but not effectively unbounded: the main behaviors are skip, retry, fallback, or fail.

## O1e8 — entry-signal parameter

- 20 completed five-minute bars — Restores the donor and forms the conventional 5/20 fast/slow pair.
- 10 completed five-minute bars — A 5/10 pair is a common faster intraday crossover.
- 15 completed five-minute bars — This supplies a moderate intraday slow window while remaining clearly slower than five bars.
- 30 completed five-minute bars — A longer slow average filters more short-term noise.
- 50 completed five-minute bars — A 5/50 pair is a familiar trend-following separation between fast and slow horizons.

This void is numerically open-ended but not effectively unbounded for fair-reading review: the listed values cover the conventional short, medium, and long intraday lookbacks.