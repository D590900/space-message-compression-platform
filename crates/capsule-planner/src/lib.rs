//! Deterministic multiple-choice knapsack planning under a strict byte budget.

use std::cmp::Ordering;
use std::collections::BTreeMap;

use thiserror::Error;

const MAX_EXACT_STATES: usize = 100_000;

/// One candidate representation for a content item.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct Candidate {
    /// Stable candidate identifier.
    pub id: String,
    /// Actual serialized bytes, excluding the request's fixed overhead.
    pub bytes: u64,
    /// Domain-specific value delivered by this candidate.
    pub utility: i64,
}

/// All mutually exclusive representations for one content item.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct Item {
    /// Stable content identifier.
    pub id: String,
    /// Whether exactly one representation must be selected.
    pub required: bool,
    /// Available quality-gated candidates.
    pub candidates: Vec<Candidate>,
}

/// Planner input.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PlanRequest {
    /// Full capsule budget.
    pub budget_bytes: u64,
    /// Exact header/index/manifest/ECC overhead not represented by candidates.
    pub fixed_overhead_bytes: u64,
    /// Items in stable input order.
    pub items: Vec<Item>,
}

/// Selected representation and explanation for one item.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct Selection {
    /// Content identifier.
    pub item_id: String,
    /// Candidate identifier, or `None` for an omitted optional item.
    pub candidate_id: Option<String>,
    /// Bytes contributed.
    pub bytes: u64,
    /// Utility contributed.
    pub utility: i64,
    /// Human-readable deterministic explanation.
    pub reason: String,
}

/// Planner algorithm used.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum Solver {
    /// Exact dynamic-programming multiple-choice knapsack.
    Exact,
    /// Stable greedy fallback when the exact state cap is exceeded.
    Greedy,
}

/// Successful plan.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct Plan {
    /// Selected entries in input item order.
    pub selections: Vec<Selection>,
    /// Fixed overhead plus selected bytes.
    pub actual_bytes: u64,
    /// Total utility.
    pub total_utility: i64,
    /// Included message count.
    pub included_items: usize,
    /// Algorithm used.
    pub solver: Solver,
}

/// Planning failure.
#[derive(Clone, Debug, Error, Eq, PartialEq)]
pub enum PlannerError {
    /// Fixed overhead alone exceeds budget.
    #[error("fixed overhead exceeds capsule budget")]
    OverheadExceedsBudget,
    /// An item or candidate identifier is empty/duplicated or candidates are invalid.
    #[error("invalid planner input: {0}")]
    InvalidInput(&'static str),
    /// Required items have no feasible combined selection.
    #[error("required items do not fit within the capsule budget")]
    RequiredItemsDoNotFit,
    /// Byte arithmetic overflowed.
    #[error("planner byte arithmetic overflow")]
    Overflow,
}

#[derive(Clone, Debug, Eq, PartialEq)]
struct State {
    utility: i64,
    included: usize,
    choices: Vec<Option<usize>>,
    stable_ids: Vec<String>,
}

/// Compute a deterministic plan.
///
/// # Errors
///
/// Returns [`PlannerError`] when input identifiers are invalid, fixed overhead
/// exceeds the budget, required items cannot fit, or byte/utility arithmetic overflows.
pub fn plan(request: &PlanRequest) -> Result<Plan, PlannerError> {
    validate(request)?;
    let capacity = request
        .budget_bytes
        .checked_sub(request.fixed_overhead_bytes)
        .ok_or(PlannerError::OverheadExceedsBudget)?;
    match exact(request, capacity) {
        Ok(Some(result)) => materialize(request, result.0, result.1, Solver::Exact),
        Ok(None) => greedy(request, capacity),
        Err(error) => Err(error),
    }
}

fn validate(request: &PlanRequest) -> Result<(), PlannerError> {
    if request.fixed_overhead_bytes > request.budget_bytes {
        return Err(PlannerError::OverheadExceedsBudget);
    }
    let mut item_ids = std::collections::BTreeSet::new();
    for item in &request.items {
        if item.id.is_empty() || !item_ids.insert(item.id.as_str()) {
            return Err(PlannerError::InvalidInput(
                "item IDs must be non-empty and unique",
            ));
        }
        if item.required && item.candidates.is_empty() {
            return Err(PlannerError::InvalidInput(
                "required item has no candidates",
            ));
        }
        let mut candidate_ids = std::collections::BTreeSet::new();
        for candidate in &item.candidates {
            if candidate.id.is_empty() || !candidate_ids.insert(candidate.id.as_str()) {
                return Err(PlannerError::InvalidInput(
                    "candidate IDs must be non-empty and unique per item",
                ));
            }
        }
    }
    Ok(())
}

fn exact(request: &PlanRequest, capacity: u64) -> Result<Option<(u64, State)>, PlannerError> {
    let mut states = BTreeMap::from([(
        0_u64,
        State {
            utility: 0,
            included: 0,
            choices: Vec::new(),
            stable_ids: Vec::new(),
        },
    )]);
    for item in &request.items {
        let mut candidates: Vec<(usize, &Candidate)> = item.candidates.iter().enumerate().collect();
        candidates.sort_by(|left, right| left.1.id.cmp(&right.1.id));
        let mut next = BTreeMap::new();
        for (used, state) in &states {
            if !item.required {
                let mut omitted = state.clone();
                omitted.choices.push(None);
                omitted.stable_ids.push(String::new());
                insert_better(&mut next, *used, omitted);
            }
            for (candidate_index, candidate) in &candidates {
                let bytes = used
                    .checked_add(candidate.bytes)
                    .ok_or(PlannerError::Overflow)?;
                if bytes > capacity {
                    continue;
                }
                let mut selected = state.clone();
                selected.utility = selected
                    .utility
                    .checked_add(candidate.utility)
                    .ok_or(PlannerError::Overflow)?;
                selected.included += 1;
                selected.choices.push(Some(*candidate_index));
                selected.stable_ids.push(candidate.id.clone());
                insert_better(&mut next, bytes, selected);
            }
        }
        if next.is_empty() {
            return Err(PlannerError::RequiredItemsDoNotFit);
        }
        states = pareto_prune(next);
        if states.len() > MAX_EXACT_STATES {
            return Ok(None);
        }
    }
    let best = states
        .into_iter()
        .max_by(|left, right| compare_states(&left.1, &right.1).then_with(|| right.0.cmp(&left.0)))
        .ok_or(PlannerError::RequiredItemsDoNotFit)?;
    Ok(Some(best))
}

fn insert_better(states: &mut BTreeMap<u64, State>, bytes: u64, candidate: State) {
    match states.get(&bytes) {
        Some(existing) if compare_states(existing, &candidate) != Ordering::Less => {}
        _ => {
            states.insert(bytes, candidate);
        }
    }
}

fn compare_states(left: &State, right: &State) -> Ordering {
    left.utility
        .cmp(&right.utility)
        .then_with(|| left.included.cmp(&right.included))
        .then_with(|| right.stable_ids.cmp(&left.stable_ids))
}

fn pareto_prune(states: BTreeMap<u64, State>) -> BTreeMap<u64, State> {
    let mut best_so_far: Option<State> = None;
    states
        .into_iter()
        .filter_map(|(bytes, state)| {
            if best_so_far
                .as_ref()
                .is_some_and(|best| compare_states(best, &state) != Ordering::Less)
            {
                None
            } else {
                best_so_far = Some(state.clone());
                Some((bytes, state))
            }
        })
        .collect()
}

fn greedy(request: &PlanRequest, capacity: u64) -> Result<Plan, PlannerError> {
    let mut remaining = capacity;
    let mut choices = vec![None; request.items.len()];

    // Establish feasibility with the smallest stable candidate for every required item.
    for (item_index, item) in request.items.iter().enumerate() {
        if !item.required {
            continue;
        }
        let (candidate_index, candidate) = item
            .candidates
            .iter()
            .enumerate()
            .min_by_key(|(_, candidate)| (candidate.bytes, &candidate.id))
            .ok_or(PlannerError::RequiredItemsDoNotFit)?;
        remaining = remaining
            .checked_sub(candidate.bytes)
            .ok_or(PlannerError::RequiredItemsDoNotFit)?;
        choices[item_index] = Some(candidate_index);
    }

    let mut improvements = Vec::new();
    for (item_index, item) in request.items.iter().enumerate() {
        for (candidate_index, candidate) in item.candidates.iter().enumerate() {
            let baseline = choices[item_index].map_or((0_u64, 0_i64), |index| {
                let current = &item.candidates[index];
                (current.bytes, current.utility)
            });
            if candidate.bytes >= baseline.0 && candidate.utility > baseline.1 {
                improvements.push((
                    candidate.utility - baseline.1,
                    candidate.bytes - baseline.0,
                    item_index,
                    candidate_index,
                    candidate.id.as_str(),
                ));
            }
        }
    }
    improvements.sort_by(|left, right| {
        let left_den = left.1.max(1);
        let right_den = right.1.max(1);
        (i128::from(right.0) * i128::from(left_den))
            .cmp(&(i128::from(left.0) * i128::from(right_den)))
            .then_with(|| right.0.cmp(&left.0))
            .then_with(|| left.1.cmp(&right.1))
            .then_with(|| left.4.cmp(right.4))
    });
    for (_, extra_bytes, item_index, candidate_index, _) in improvements {
        if extra_bytes <= remaining {
            remaining -= extra_bytes;
            choices[item_index] = Some(candidate_index);
        }
    }
    materialize(
        request,
        capacity - remaining,
        State {
            utility: 0,
            included: choices.iter().flatten().count(),
            stable_ids: Vec::new(),
            choices,
        },
        Solver::Greedy,
    )
}

fn materialize(
    request: &PlanRequest,
    selected_bytes: u64,
    state: State,
    solver: Solver,
) -> Result<Plan, PlannerError> {
    let mut total_utility = 0_i64;
    let selections = request
        .items
        .iter()
        .zip(state.choices)
        .map(|(item, choice)| match choice {
            Some(index) => {
                let candidate = &item.candidates[index];
                total_utility = total_utility
                    .checked_add(candidate.utility)
                    .ok_or(PlannerError::Overflow)?;
                Ok(Selection {
                    item_id: item.id.clone(),
                    candidate_id: Some(candidate.id.clone()),
                    bytes: candidate.bytes,
                    utility: candidate.utility,
                    reason: format!(
                        "selected {} for utility {} at {} bytes within the global optimum",
                        candidate.id, candidate.utility, candidate.bytes
                    ),
                })
            }
            None => Ok(Selection {
                item_id: item.id.clone(),
                candidate_id: None,
                bytes: 0,
                utility: 0,
                reason: "optional item omitted because its candidates did not improve the constrained plan"
                    .to_owned(),
            }),
        })
        .collect::<Result<Vec<_>, PlannerError>>()?;
    let actual_bytes = request
        .fixed_overhead_bytes
        .checked_add(selected_bytes)
        .ok_or(PlannerError::Overflow)?;
    debug_assert!(actual_bytes <= request.budget_bytes);
    Ok(Plan {
        included_items: selections
            .iter()
            .filter(|selection| selection.candidate_id.is_some())
            .count(),
        selections,
        actual_bytes,
        total_utility,
        solver,
    })
}
