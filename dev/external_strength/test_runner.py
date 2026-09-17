"""Harness-only scripted checks. Neither frozen engine is imported or changed."""
import unittest
import chess
import run_match as match


class FakeClock:
    def __init__(self):
        self.value = 0.0

    def __call__(self):
        return self.value


class Scripted:
    def __init__(self, moves, clock, elapsed=0.010):
        self.moves = iter(moves)
        self.clock = clock
        self.elapsed = elapsed
        self.calls = []

    def move(self, fen, remaining):
        self.calls.append((fen, remaining))
        self.clock.value += self.elapsed
        move = next(self.moves)
        if isinstance(move, Exception):
            raise move
        return move


def play(fen, opening, white, black, elapsed=0.010):
    clock = FakeClock()
    agents = {True: Scripted(white, clock, elapsed), False: Scripted(black, clock, elapsed)}
    slot = {"slot": "test", "pair": 1, "opening_id": "scripted", "fen": fen,
            "opening_plies": opening, "white": "CAND", "black": "BASE", "astra_colour": "white",
            "contract": "competition_600", "initial_clock_ms": 120000, "increment_ms": 500}
    return match.run_loop(agents, slot, now=clock)[0], agents


class ContractTests(unittest.TestCase):
    def test_allowances_and_boundary(self):
        for opening in (0, 8, 40, 599, 600):
            self.assertEqual(match.CONTRACT.opening_allowance(opening), 600 - opening)
            self.assertTrue(match.CONTRACT.cap_reached(opening, 600 - opening))
            if opening < 600:
                self.assertFalse(match.CONTRACT.cap_reached(opening, 599 - opening))
        with self.assertRaises(ValueError):
            match.CONTRACT.validate_opening(601)

    def test_cap_ignores_material(self):
        record, _ = play("4k3/8/8/8/8/8/8/R2QK2R w KQ - 0 1", 600, [], [])
        self.assertEqual(record["termination"], "ply_cap_draw")
        self.assertEqual(record["result"], "1/2-1/2")
        self.assertEqual(record["total_plies"], 600)

    def test_mate_on_ply_600(self):
        record, _ = play("r3k3/8/8/8/8/8/5PPP/6K1 b - - 0 300", 599, [], ["a8a1"])
        self.assertEqual(record["termination"], "checkmate")
        self.assertEqual(record["result"], "0-1")
        self.assertEqual(record["total_plies"], 600)
        self.assertEqual(record["engine_plies"], 1)
        self.assertEqual(record["contract"], "competition_600")
        self.assertAlmostEqual(record["final_clocks_ms"]["black"], 120490)

    def test_stalemate_final_ply(self):
        record, _ = play("7k/5Q2/6K1/8/8/8/8/8 w - - 0 1", 599, ["f7e6"], [])
        self.assertEqual(record["termination"], "stalemate")
        self.assertEqual(record["total_plies"], 600)

    def test_insufficient_material(self):
        record, _ = play("4k3/8/8/8/8/8/4r3/4K3 w - - 0 1", 10, ["e1e2"], [])
        self.assertEqual(record["termination"], "insufficient_material")
        self.assertEqual(record["total_plies"], 11)

    def test_illegal_no_increment(self):
        record, _ = play(chess.STARTING_FEN, 0, ["a1h8"], [])
        self.assertEqual(record["termination"], "illegal")
        self.assertEqual(record["engine_plies"], 0)
        self.assertAlmostEqual(record["final_clocks_ms"]["white"], 119990)
        self.assertEqual(record["legal_moves_by_colour"]["white"], 0)

    def test_flag_no_increment(self):
        record, _ = play(chess.STARTING_FEN, 0, ["e2e4"], [], elapsed=120.001)
        self.assertEqual(record["termination"], "flag")
        self.assertEqual(record["engine_plies"], 0)
        self.assertLess(record["final_clocks_ms"]["white"], 0)

    def test_exception_is_chess_loss(self):
        record, _ = play(chess.STARTING_FEN, 0, [match.EngineFailure("crash", "injected")], [])
        self.assertEqual(record["termination"], "crash")
        self.assertEqual(record["result"], "0-1")

    def test_clocks_passed_and_increment_after_legal(self):
        record, agents = play(chess.STARTING_FEN, 597, ["e2e4", "g1f3"], ["e7e5"])
        self.assertEqual(record["termination"], "ply_cap_draw")
        self.assertEqual(record["engine_plies"], 3)
        self.assertEqual([call[1] for call in agents[True].calls], [120000, 120490])
        self.assertEqual([call[1] for call in agents[False].calls], [120000])
        self.assertAlmostEqual(record["final_clocks_ms"]["white"], 120980)
        self.assertAlmostEqual(record["final_clocks_ms"]["black"], 120490)

    def test_threefold_autoclaim_and_history_start(self):
        record, _ = play(chess.STARTING_FEN, 0, ["g1f3", "f3g1", "g1f3", "f3g1"],
                         ["g8f6", "f6g8", "g8f6", "f6g8"])
        self.assertEqual(record["termination"], "threefold_repetition")
        self.assertEqual(record["engine_plies"], 7)

    def test_fifty_move_and_mate_precedence(self):
        record, _ = play("6k1/8/8/8/8/8/8/KQ6 w - - 100 51", 100, [], [])
        self.assertEqual(record["termination"], "fifty_moves")
        record, _ = play("7k/6Q1/5K2/8/8/8/8/8 b - - 100 51", 600, [], [])
        self.assertEqual(record["termination"], "checkmate")
        self.assertEqual(record["result"], "1-0")

    def test_schedule(self):
        schedule = match.make_schedule()
        self.assertEqual(len(schedule["openings"]), 20)
        self.assertEqual(len(schedule["games"]), 40)
        for pair in range(1, 21):
            games = [game for game in schedule["games"] if game["pair"] == pair]
            self.assertEqual(len(games), 2)
            self.assertEqual(games[0]["fen"], games[1]["fen"])
            self.assertEqual({game["astra_colour"] for game in games}, {"white", "black"})


def run_tests():
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(ContractTests)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if not result.wasSuccessful():
        raise AssertionError("Harness self-tests failed; do not launch games")
    return {"tests": result.testsRun, "failures": len(result.failures), "errors": len(result.errors)}


if __name__ == "__main__":
    run_tests()
