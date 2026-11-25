"""Offline scripted demonstration."""

import argparse

from indubio.core.engine import SimulationEngine
from indubio.core.models import (
    Actor, FileMotion, Mode, MovePhase, Phase, Proposal, Role, RuleOnMotion,
    SimulationConfig, Speak,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="InDubioProAgente experimental kernel")
    parser.add_argument("command", choices=["demo", "scenario-demo", "floor-demo"])
    parser.add_argument("--mode", choices=[mode.value for mode in Mode], default="realistic")
    parser.add_argument(
        "--perspective", metavar="ACTOR_ID",
        help="also print the redacted projection for one synthetic actor",
    )
    args = parser.parse_args()
    if args.command in {"scenario-demo", "floor-demo"}:
        # Imported lazily so the default demo path is unchanged.
        from indubio.scenarios.demo import run_floor_demo, run_scenario_demo

        run = run_scenario_demo if args.command == "scenario-demo" else run_floor_demo
        engine = run(Mode(args.mode))
        for event in engine.events:
            print(event.model_dump_json())
        _print_perspective(parser, engine, args.perspective)
        return
    actors = [
        Actor(actor_id="judge", role=Role.JUDGE, display_name="Judge"),
        Actor(actor_id="defense", role=Role.DEFENSE, display_name="Defense"),
        Actor(actor_id="defendant", role=Role.DEFENDANT, display_name="Defendant"),
    ]
    engine = SimulationEngine(actors, SimulationConfig(mode=Mode(args.mode)))
    actions = [
        Proposal(actor_id="judge", action=MovePhase(destination=Phase.EVIDENCE)),
        Proposal(actor_id="defendant", action=Speak(text="I will answer only selected questions.")),
        Proposal(actor_id="defense", action=FileMotion(motion_id="m1", grounds="Synthetic request")),
        Proposal(actor_id="judge", action=RuleOnMotion(
            motion_id="m1", ruling="denied", reasons="Demonstrator reasons only"
        )),
        Proposal(actor_id="judge", action=MovePhase(destination=Phase.FINISHED)),
    ]
    for action in actions:
        print(engine.propose(action).model_dump_json())
    _print_perspective(parser, engine, args.perspective)


def _print_perspective(
    parser: argparse.ArgumentParser, engine: SimulationEngine, actor_id: str | None
) -> None:
    if actor_id is None:
        return
    try:
        print(engine.perspective(actor_id).model_dump_json())
    except PermissionError as error:
        parser.exit(2, f"error: {error}\n")


if __name__ == "__main__":
    main()
