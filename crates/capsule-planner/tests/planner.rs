//! Multiple-choice knapsack planner tests.

use proptest::prelude::*;
use smcp_capsule_planner::{Candidate, Item, PlanRequest, PlannerError, Solver, plan};

fn candidate(id: &str, bytes: u64, utility: i64) -> Candidate {
    Candidate {
        id: id.to_owned(),
        bytes,
        utility,
    }
}

#[test]
fn finds_global_optimum_not_local_ratio() {
    let request = PlanRequest {
        budget_bytes: 120,
        fixed_overhead_bytes: 20,
        items: vec![
            Item {
                id: "message-a".into(),
                required: true,
                candidates: vec![candidate("a-small", 20, 20), candidate("a-large", 60, 70)],
            },
            Item {
                id: "message-b".into(),
                required: true,
                candidates: vec![candidate("b-small", 20, 20), candidate("b-large", 80, 75)],
            },
        ],
    };
    let result = plan(&request).unwrap();
    assert_eq!(result.solver, Solver::Exact);
    assert_eq!(result.total_utility, 95);
    assert_eq!(result.actual_bytes, 120);
    assert_eq!(
        result.selections[0].candidate_id.as_deref(),
        Some("a-small")
    );
    assert_eq!(
        result.selections[1].candidate_id.as_deref(),
        Some("b-large")
    );
}

#[test]
fn stable_tie_break_uses_candidate_id() {
    let request = PlanRequest {
        budget_bytes: 10,
        fixed_overhead_bytes: 0,
        items: vec![Item {
            id: "message".into(),
            required: true,
            candidates: vec![candidate("z", 10, 1), candidate("a", 10, 1)],
        }],
    };
    assert_eq!(
        plan(&request).unwrap().selections[0]
            .candidate_id
            .as_deref(),
        Some("a")
    );
}

#[test]
fn rejects_impossible_required_items() {
    let request = PlanRequest {
        budget_bytes: 9,
        fixed_overhead_bytes: 0,
        items: vec![Item {
            id: "required".into(),
            required: true,
            candidates: vec![candidate("only", 10, 1)],
        }],
    };
    assert_eq!(plan(&request), Err(PlannerError::RequiredItemsDoNotFit));
}

proptest! {
    #[test]
    fn successful_plan_never_exceeds_budget(budget in 1_u64..10_000, fixed in 0_u64..1_000) {
        let request = PlanRequest {
            budget_bytes: budget,
            fixed_overhead_bytes: fixed,
            items: vec![Item {
                id: "optional".into(),
                required: false,
                candidates: vec![candidate("candidate", budget / 2, 10)],
            }],
        };
        if let Ok(result) = plan(&request) {
            prop_assert!(result.actual_bytes <= budget);
        }
    }
}
