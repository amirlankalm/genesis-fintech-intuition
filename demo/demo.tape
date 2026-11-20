# Records demo/demo.mp4 with VHS (https://github.com/charmbracelet/vhs): vhs demo/demo.tape
# Run from the repository root after `uv sync`. Every command shown is real and runs live.

Output demo/demo.mp4

Set Shell "bash"
Set FontSize 17
Set Width 1600
Set Height 960
Set Padding 24
Set Theme "Catppuccin Mocha"
Set TypingSpeed 35ms
Set PlaybackSpeed 1.0

Hide
Type "export PS1='\[\e[1;32m\]intuition\[\e[0m\]:\[\e[1;34m\]genesis-fintech\[\e[0m\]$ ' DEMO_PACE=1.2 && clear"
Enter
Sleep 500ms
Show

Type "# Genesis FinTech · team Intuition · an RL environment for financial-audit models"
Enter
Sleep 2s
Type "# 1. A company with hidden errors, the agent's tools, a solver, and attacks on the reward"
Enter
Sleep 1s
Type "uv run python demo/demo.py"
Enter
Sleep 40s

Type "clear"
Enter
Type "# 2. The jury's interface: four baselines through judge_adapter.py, closed mode, 20 shipped episodes"
Enter
Sleep 1s
Type "uv run python tools/judge_run.py --summary /tmp/demo_summary.json --trajectories /tmp/demo_trajectories.jsonl | tail -9"
Enter
Sleep 9s

Type "clear"
Enter
Type "# 3. Every official check, re-implemented blind from the published definitions, through the adapter only"
Enter
Sleep 1s
Type "uv run pytest tests/jury -p no:cacheprovider 2>&1 | tail -3"
Enter
Sleep 11s

Type "clear"
Enter
Type "# 4. Isolation: a hostile policy tries to read the answer key, write, connect, fork, signal the evaluator"
Enter
Sleep 1s
Type "uv run python -m genesis_audit probe | head -16"
Enter
Sleep 8s
Type "# held: true. One known macOS gap is shown as ok and documented: a same-user process can read the evaluator's initial environment, so nothing secret is put there"
Enter
Sleep 5s

Type "clear"
Enter
Type "# 5. The trajectories the case asks for: episode_id, step, action, observation, reward, terminated, truncated"
Enter
Sleep 1s
Type `head -n 3 trajectories.jsonl | cut -c 1-240`
Enter
Sleep 6s
Type "wc -l trajectories.jsonl"
Enter
Sleep 4s

Type "clear"
Enter
Type "# One command runs all of it offline in a container:  make docker-check"
Enter
Sleep 4s
