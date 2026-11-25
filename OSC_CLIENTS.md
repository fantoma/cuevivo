# OSC clients and master changes

Programs that send OSC commands to Cuevivo, such as **Script Follower**, normally point at a fixed IP
address: the master's. When Cuevivo runs with secondary instances (slave or redundancy) and the master goes
down, a secondary can be promoted (by hand or automatically). The promoted instance has a different IP address,
so those programs would keep sending their cues to a machine that is no longer there.

With this small protocol the programs introduce themselves to Cuevivo, and the new master tells them where to
send their commands. Everything is OSC over UDP: the program talks to Cuevivo's OSC input port
(Settings › OSC, default 53000), and Cuevivo answers on a *return port* the program chooses.

## Messages

The addresses use the historical `/cuestage` namespace (the program was called CueStage). Cuevivo also accepts
the same messages under `/cuevivo` (e.g. `/cuevivo/client/hello`) and answers a program in the namespace it used.

| Direction | Address | Arguments |
|---|---|---|
| program → Cuevivo | `/cuestage/client/hello` | `app` (s), `version` (s), `computer name` (s), `return port` (i), `client id` (s), `profile id` (s, optional) |
| Cuevivo → program | `/cuestage/client/ack` | `instance name` (s), `OSC port` (i), `group members` (s, comma-separated IPs of the secondary instances) |
| new master → program | `/cuestage/master` | `new IP` (s), `OSC port` (i), `instance name` (s), `old master IP` (s, may be empty) |
| program → new master | `/cuestage/client/moved` | `client id` (s), `moved profile ids` (s, comma-separated) |
| program → Cuevivo | `/cuestage/client/bye` | `client id` (s) |

- The program sends `hello` when it starts and then every few seconds (Script Follower: every 5 s). The `hello`
  also works as a keep-alive: a program that has not been heard from for 30 s is forgotten.
- Cuevivo answers every `hello` with an `ack` sent to the sender's address and the return port. The status bar
  shows when a new program connects.
- The master passes the list of connected programs to its secondary instances with the state message it already
  sends at least once per second.
- When a secondary is **promoted** (*Leave slave mode*, or automatically when the master is lost), it sends
  `/cuestage/master` to every program the old master knew. The IP is the one this machine uses to reach that
  program, and the OSC port is this instance's own OSC input port. If OSC input is switched off on the
  promoted instance, nothing is sent.
- The program moves its Cuevivo destinations to the new address, answers `moved`, and from then on sends its
  `hello` messages to the new master, which in turn passes them on to its own secondaries.

## Active cues (show them in the program)

A program that has introduced itself with `hello` can show Cuevivo's **active cues** in its own interface, like
the *Active cues* panel: Cuevivo pushes the state, the program draws it and can stop or pause single cues.

| Direction | Address | Arguments |
|---|---|---|
| program → Cuevivo | `/cuestage/client/active/subscribe` | `client id` (s), `rate` (f, updates per second while cues run, default 4, 0.5…20), `options` (s, optional, comma-separated: `nogroups`, `media`) |
| program → Cuevivo | `/cuestage/client/active/unsubscribe` | `client id` (s) |
| Cuevivo → program | `/cuestage/active` | `state` (s, JSON, see below) |
| program → Cuevivo | `/cuestage/client/active/stop` | `cue id` (s), `fade` (f, optional, default: the show's stop fade) |
| program → Cuevivo | `/cuestage/client/active/pause` | `cue id` (s) — pause / resume (toggle) |

- `subscribe` must come after a `hello` (Cuevivo needs the return port); it can be repeated to change rate or
  options. The subscription lives as long as the program keeps sending its `hello` (30 s without = forgotten),
  so a program should simply send `subscribe` again after every reconnection or master change.
- Cuevivo answers immediately, then sends `/cuestage/active` **at once when something changes** (a cue starts,
  stops, pauses, fades out, the standby moves), **at the requested rate while cues are active** (the times move)
  and every 2 s when nothing is active.
- Options: `nogroups` leaves out group cues (their cues stay), `media` keeps only audio, video, image, PDF and
  text cues.
- Stop and pause go through the normal commands, so on a redundancy master they are replicated as usual.

State (one JSON object per message, at most ~60 KB: if the list does not fit, the last cues are left out and
`more` says how many):

```json
{"v": 1, "instance": "Regia", "paused_all": false,
 "standby": {"id": "…", "number": "12", "name": "12 Rain", "list": "MAIN"},
 "cues": [
  {"id": "…", "number": "10", "name": "10 Storm", "type": "audio", "list": "MAIN", "color": "#3464aa",
   "group": false, "in_group": true, "state": "run", "elapsed": 12.4, "total": 95.0, "remaining": 82.6,
   "progress": 0.131, "status": "", "fading": false},
  {"id": "…", "number": "11", "name": "11 Bell", "type": "audio", "list": "Effects", "color": "#a05a2c",
   "group": false, "in_group": false, "state": "wait", "wait": 3.2, "elapsed": 0.0, "total": null,
   "remaining": null, "progress": null, "status": ""}]}
```

- `state`: `wait` (in pre-wait, `wait` = seconds left), `run`, `paused`. `total`/`remaining`/`progress` are
  `null` for cues without an end (infinite loops, images until stopped…). `status` is the cue's own text
  (e.g. “line 3/12” for a text sequence, “SRT en · 14/320”). `fading` = the cue is fading out to stop.
- `name` is the cue label as shown in Cuevivo (number and name); `color` is the colour of its list.
- `v` is the protocol version: fields may be added in the future, a program must ignore the unknown ones.

## Safety

Anyone on the network can send OSC. A program should apply `/cuestage/master` on its own only when it comes
from a known instance: the old master, or one of the `group members` listed in the last `ack`. In any other
case it should ask the operator. Script Follower ignores the message if it concerns none of its profiles.

## Script Follower

To show the active cues, Script Follower subscribes after each `hello` (see *Active cues* above) and draws
the list with progress bars and ■ / ❚❚ buttons that send `stop` / `pause`.

Settings › OSC › **Cuevivo: master change**. You can switch the feature on or off, choose the return port
(default 53100, or the next free port if that one is busy), and see whether each Cuevivo profile is connected.
Cuevivo profiles that pointed to the old master (or to a member of its group) are moved automatically.
Profiles with other plugins (QLab, ChamSys…) are never touched.
