# Chessathon engine design

This is an independently written pure-Python engine. It uses the installed
`python-chess` package for legal moves and board push/pop. No third-party chess
engine, port, translation, published engine source, binary, neural model, opening
database or tablebase was used. Piece-square tables come from original formulas
in `agent.py`, not from a published value set. All source remains readable.

## Representation and initialization

An early microbenchmark measured legal generation + push + position key + pop
at approximately 238,000 operations/second on the development machine. Keeping
python-chess avoided introducing move-generation bugs during the two-hour sprint.
Material and piece-square scores are incrementally maintained in the search;
push/pop restores a single shared board. All static tables are built at import,
inside the separate initialization allowance. The runtime reads and writes no
files and is independent of the current working directory.

## Search

Iterative deepening negamax uses alpha-beta and principal variation search.
A bounded transposition table records depth, bound type, best move, halfmove
clock and generation. Mate scores are adjusted by search ply on storage and
retrieval, making shorter wins and longer losses preferable. Move ordering uses
the TT move, captures by victim/attacker value, promotions, killers and history.
Generation is staged: a cutoff after an early move avoids building the later
quiet-move list. A separate counter records every yielded legal move; only a
zero count denotes mate/stalemate. The final main search has no move-skipping
pruning. A conservative futility experiment was rejected on timing evidence.
Conservative late move reductions re-search moves that improve alpha. Null move
is disabled in check and in king-and-pawn-only positions. Artificial null lines
do not create real repetition claims. Narrow aspiration windows widen on failure.

At the horizon, quiescence searches captures and every promotion, including quiet
underpromotions. In check it searches all legal evasions and forbids stand-pat.
At least two quiescence plies are searched before considering static exchange
pruning of materially losing captures. The original exchange routine handles
x-rays and pinned recapturers and was checked against legal recapture minimax.
Checks, evasions and promotions are never removed by delta/exchange pruning.
Empty legal move sets detect checkmate and stalemate directly; game-over APIs
are never called inside search. Checking moves can extend the search, with a
limit on cumulative extensions. A hard ply limit prevents runaway recursion.

## Evaluation

Material and original formula-based piece-square tables interpolate between
middlegame and endgame according to remaining non-pawn material. Cheap bitboard
terms reward bishop pairs, passed pawns, rook files and king pawn shelter, and
penalize isolated/doubled pawns. Pawn structure is cached by the two pawn masks;
bonuses that depend on current blockers are recomputed. Endgame king tables
centralize the king.
Bare-king endings reward pushing the defender toward the edge and bringing the
attacking king closer. Clearly insufficient material is scaled toward a draw.
Scores fade near the fifty-move limit so the engine prefers irreversible progress.

## History and adjudication

The referee starts a fresh process for each game. The first supplied position is
the beginning of recorded history. Each call records the current counter-free
position unless it repeats the preceding call (a retry). Every returned move,
including an exception fallback, records its resulting position. Pawn moves and
captures or permanent castling-rights loss discard irrelevant old history;
the supplied halfmove clock bounds it.
Keys use `Board._transposition_key()`, with an equivalent bitboard fallback.
Irrelevant en-passant targets and FEN move counters do not alter identity.
Retries replace the tentative post-move record. Irreversibility is determined
against the supplied pre-move board, so retrying a move that loses castling rights
does not accidentally restore or discard older history.

Search counts occurrences in recorded history plus the current path. Only the
third occurrence is a repetition draw. A second occurrence remains searchable.
Draw contempt discourages draws when winning and values escape when losing.
Halfmove clocks at least 100 are draws within search; actual checkmate takes
precedence. The public interface still returns a legal move from positions with
legal moves, even if an automatic draw rule would already end the game.

## Time and failure handling

`time_left_ms` excludes the 500 ms increment. The allocator never borrows that
increment; it keeps a 150 ms reserve. The soft budget is remaining seconds / 35 + 0.75 times
the increment; hard is 1.6 times soft, capped at remaining / 8 and the available
clock after the reserve. Below 1.5 seconds the existing low-clock path takes over.
Worst-case arithmetic simulations check sustainable increment play over long
games. The soft limit and observed iteration growth decide whether to start another
depth. Best-move changes and falling scores allow modest extension, bounded by
the hard limit. `perf_counter` checks abort search regularly, more frequently at
low clocks. A legal fallback is selected before search; single-move positions
return immediately. Below 100 ms no search runs. Partial iterations can replace
the previous result only with a completed root search that scores better.

The API catches internal exceptions, reconstructs the supplied position and
returns and records a legal fallback. Only positions with no legal move return
`0000`. The 600-ply cap is a draw, so conversion tests check actual mates rather
than trusting a favorable evaluation. Local NPS is a best-case measurement;
the target is one AMD EPYC core at 2.6 GHz.
