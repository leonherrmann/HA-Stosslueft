# Stoßlüften

A Home Assistant integration that answers one question: **should I open every window right now?**

It compares each room against the outdoor conditions, scores the flat from 0 to 100 overall and room
by room, and — because every window in the flat has a contact sensor — notices when you actually air
out and reports how much cooler it got, in total and per room.

A dashboard card ships with the integration, so it is one HACS install and no Lovelace resource to
add by hand.

## What you get

| Entity | What it is |
| --- | --- |
| `sensor.<name>_airing_score` | The overall score, 0–100. Every attribute the card needs lives here. |
| `sensor.<name>_<room>_airing_score` | Per-room score, with the reasoning in its attributes. |
| `sensor.<name>_indoor_temperature` | Average across all configured rooms. |
| `sensor.<name>_last_airing_cooldown` | How much the flat cooled during the last airing, with the per-room breakdown. |
| `sensor.<name>_<room>_airing_cooldown` | The same figure per room, so you can graph it. |
| `sensor.<name>_airing_cooldown_today` | Sum of every session since midnight. |
| `binary_sensor.<name>_airing_recommended` | On when the score clears your threshold. |
| `binary_sensor.<name>_airing_active` | On while a window is open, with live progress. |

Every finished session also fires a `stosslueft_airing_finished` event — see
[Automations](#automations).

## Installation

### HACS

1. HACS → ⋮ → *Custom repositories* → add `https://github.com/leonherrmann/HA-Stosslueft`,
   category **Integration**.
2. Install *Stoßlüften* and restart Home Assistant.
3. *Settings → Devices & services → Add integration → Stoßlüften*.

### Manual

Copy `custom_components/stosslueft` into your `config/custom_components/` directory and restart.

## Setup

Setup asks two things:

1. **Where the outdoor readings come from.** A `sensor.*` or a `weather.*` entity both work; humidity
   is optional and configured separately. A thermometer on your own balcony beats a forecast from a
   station several kilometres away.
2. **Which rooms to watch.** The integration scans your areas and proposes one room per area,
   matching up the temperature sensor, humidity sensor and window contact it finds there. Untick what
   you do not want.

Everything is editable afterwards under *Configure*: the tuning knobs, the individual rooms and their
sensors, and a *Look for new rooms* action that re-runs the scan.

## The card

Add *Stoßlüften* from the card picker. It only needs the overall score sensor:

```yaml
type: custom:stosslueft-card
entity: sensor.stossluften_airing_score
# optional
name: Lüften?
show_rooms: true
show_last_session: true
```

It shows the gauge with a tick at your recommendation threshold, the indoor/outdoor comparison and
suggested duration, a live banner while a window is open, the per-room breakdown, and the last
session's result. English and German are built in; it follows your Home Assistant language.

## How the score works

Opening the windows drags every room towards the outdoor temperature. So the useful question is not
"how big is the difference?" but "does that drag move the room closer to where I want it, and does it
dry the room out or wet it?". Scoring the *change* is what lets one formula work in July and in
January.

**Temperature.** From the indoor/outdoor difference the model derives a sensible airing duration
(big difference → short airing), how much air is exchanged in that time, and how much of the drop
survives once the walls give their heat back. It then compares how far the room is from your target
temperature before and after. Getting closer scores positive, overshooting scores negative. A
configurable comfort band around the target keeps small differences from moving the number around.

**Humidity** (optional). Relative humidity is the wrong measure here — 90 % at 2 °C carries far less
water than 55 % at 26 °C — so the model compares *absolute* humidity to decide whether airing dries
the flat or wets it. Its weight starts low and climbs steeply once a room passes 60 % relative
humidity, which is what makes a short winter airing worthwhile despite the heat it costs. Set the
humidity weight to 0 to turn this off entirely; rooms without a humidity sensor are scored on
temperature alone.

**Rain.** If your outdoor source is a weather entity, the score is capped at 40 while it rains. You
can switch that off.

The overall score is the mean of the room scores, so one hot room cannot hide behind five comfortable
ones. The wording and the suggested duration come from scoring the flat as a whole.

Some worked examples with the default target of 21 °C:

| Situation | Inside | Outside | Score |
| --- | --- | --- | --- |
| Summer night | 26 °C / 55 % | 18 °C / 80 % | 94 — air out, 15 min |
| Summer afternoon | 24 °C | 32 °C | 0 — keep them shut |
| Muggy and warm | 24 °C / 70 % | 22 °C / 95 % | 0 — would import moisture |
| Winter, damp room | 21 °C / 68 % | 2 °C / 90 % | 84 — 6 min to dry it out |
| Winter, comfortable | 21 °C / 45 % | 2 °C / 90 % | 20 — just wastes heat |

## Airing detection

A session starts when the first window contact opens and ends when the last one closes. Because
indoor sensors keep falling for a while after the windows are shut, the result is only drawn after a
settle time (10 minutes by default) — that is what makes the number honest.

Two details worth knowing:

- **Every room is measured, not just the ones with an open window.** The hallway cools too, and you
  asked about the flat.
- **Reopening a window during the settle time continues the same session** rather than starting a
  second one, so working through the flat window by window is reported as one airing.

Sessions shorter than two minutes are discarded, and a contact going `unavailable` and back (a radio
stick restarting) never starts a session. An airing that spans a Home Assistant restart is picked
back up.

Cooldowns are reported in °C as a *difference*, which is why those sensors carry no device class:
a 2 °C drop is 2 K, and converting it to Fahrenheit would be wrong.

## Automations

```yaml
automation:
  - alias: Airing report
    triggers:
      - trigger: event
        event_type: stosslueft_airing_finished
    conditions:
      - "{{ trigger.event.data.at_night and trigger.event.data.delta > 1 }}"
    actions:
      - action: notify.mobile_app
        data:
          title: >-
            Cooled down {{ trigger.event.data.delta | round(1) }} K
          message: >-
            {{ trigger.event.data.duration_minutes | round }} min ·
            {% for room in trigger.event.data.rooms if room.delta %}
            {{ room.name }} −{{ room.delta | round(1) }} K{{ ", " if not loop.last }}
            {%- endfor %}
```

The event payload carries `started`, `ended`, `duration_minutes`, `at_night`, `outdoor_temperature`,
`delta` and a `rooms` list with each room's `temperature_start`, `temperature_min`,
`temperature_end`, `delta`, `duration_minutes` and whether it was `aired` itself.

To be told when it becomes worth airing, trigger on
`binary_sensor.<name>_airing_recommended` turning on.

## Settings

| Setting | Default | What it does |
| --- | --- | --- |
| Target temperature | 21 °C | What every room is scored against. |
| Comfort band | 1.5 K | How far from the target still counts as comfortable. |
| Humidity weight | 0.2 | Base weight of the humidity comparison; 0 turns it off. |
| Recommendation threshold | 65 | Where `binary_sensor.*_airing_recommended` flips. |
| Settle time | 10 min | How long to wait after the windows shut before reporting. |
| Shortest session | 2 min | Anything briefer is not counted as airing. |
| Rain guard | on | Cap the score while a weather entity reports rain. |

## Development

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r tests/requirements_test.txt
pytest tests/ -v
```

`scoring.py` imports nothing from Home Assistant, so the model can be exercised on its own.

## Licence

MIT — see [LICENSE](LICENSE).
