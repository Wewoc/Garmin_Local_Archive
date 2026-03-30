![Garmin Local Archive](screenshots/Banner.png)

 Garmin Local Archive — Correlation Engine ✨

> *Module name: `correlation_engine.py`*
>
> "Correlation is not causation. But it's more fun."
>
> ⚠️ This document is not on the roadmap. It will never be on the roadmap.
> It exists because someone asked "what other curious ideas do you have?"
> at 23:00 after a very long session.

---

## On first startup

`correlation_engine.py` asks for three things.

Not for age-adjusted VO2max reference ranges.

1. **Date of birth** — for star sign
2. **Place of birth** — for ascendant
3. **Exact time of birth** — for ascendant (astrologically incorrect without it)

Three mandatory fields. More than the Garmin first-time setup.

If the user doesn't know their birth time: `correlation_engine.py` refuses to calculate the ascendant and displays a warning:
*"Without birth time, ascendant calculation is astrologically invalid. Please consult your birth certificate or your mother."*

---

## Astrological

| Feature | Data source | Note |
|---|---|---|
| Star sign correlation | Birth date | "Scorpio shows statistically higher stress levels. N=1. Yours." |
| Rising sign | Birth date + birth location | "Your rising sign may explain the Monday dip" |
| Moon sign | Calculable | Because one star sign is never enough |
| Mercury in retrograde | Calculable | With a serious axis label and zero explanation |
| Planetary conjunctions | NASA ephemeris, free | "Jupiter conjunct Saturn: HRV unusually stable. Coincidence?" |
| Compatible signs | Both partners' birth dates | "Compatible signs show better sleep synchronization" — for couples who both wear Garmin |
| Retrograde anything | Calculable | Flexible — applies whenever data looks bad |
| Daily biometric horoscope | Crystal Energy + Acupuncture Index + Star sign + Ascendant | See Appendix A. ✨ |

---

## Cosmic

| Feature | Data source | Note |
|---|---|---|
| Moon phases | Calculable, no API | 🌕 People believe it anyway |
| Full moon correlation index | Calculable | Percentage of low-HRV days that fall on a full moon |
| Geomagnetic activity | NOAA Kp-Index, free | ⚡ Nobody knows why. That's the point. |
| Sunspot activity | NASA, free | Sounds serious. Isn't. |
| Cosmic ray intensity | Available. Somewhere. | Measurable, meaningless, impressive-sounding |
| Schumann resonance | Earth frequency | Earth frequency meets HRV — nobody knows why |
| Cosmic background radiation | The data exists | Why not. |

---

## Biological-Esoteric

| Feature | Data source | Note |
|---|---|---|
| Biorhythm | Birth date | Physical / Emotional / Intellectual — 1970s classic, fully calculable |
| Blood type correlation | User input | "Type A shows lower HRV on Tuesdays" |
| Maria Thun moon calendar | Calculable | Developed for gardening. Repurposed for HRV. |
| Fibonacci sleep rhythm | Existing sleep data | "Your deep sleep follows the golden ratio. Probably." |
| Crystal energy index | None | Pseudo-deterministic: uses the hash of `garmin_raw_YYYY-MM-DD.json` as seed. The energy is always the same on the same day. Nobody can explain the formula. *"Crystal energy cannot be measured. This number is made up. But so is astrology."* |
| Acupuncture school selector | HRV + Stress + Crystal Energy Index | See below. ✨ |
| Ayurvedic dosha analysis | HRV + Stress + Body Battery | See below. ✨ |
| Daily biometric supplement plan | HRV night + Stress yesterday + Sleep duration + Acupuncture index + Crystal Energy | See Appendix B. Morning / Lunch / Evening. Globuli, Cell Salt, or Bach Flower. Dosage: by intuition. ✨ |
| Chakra status | Resting HR + HRV + Stress + Body Battery + Sleep + Steps + Readiness | See below. ✨ |
| Feng Shui sleep direction | HRV + Crystal Energy + Ascendant | See below. ✨ |

### Acupuncture School Selector

Different books define acupuncture points differently. Rather than picking one arbitrarily, `correlation_engine.py` determines the most appropriate school for each day algorithmically:

```python
school_index = (hrv % 10 + stress % 10 + crystal_energy % 10) % 4
```

| Value | School | Note |
|---|---|---|
| 0 | TCM — Traditional Chinese Medicine | The classic |
| 1 | Meridian School (Japan) | More precise. Apparently. |
| 2 | Korean Hand Acupuncture | Everything is in the hand |
| 3 | Ayurvedic Interpretation ✨ | Not actually acupuncture. The algorithm doesn't know that. |

It looks like serious mathematics. It is serious mathematics. Applied to a completely arbitrary outcome.

Output shown as: *"Based on your biometric signature, the TCM school is most applicable today."*

The user never learns why. The algorithm cannot be wrong. No school can be disproven. This is intentional.

---

### Ayurvedic Dosha Analysis

Ayurveda identifies three fundamental bio-energies — Doshas — that govern all physical and mental processes. `correlation_engine.py` determines the dominant Dosha from your daily biometrics:

```python
vata  = max(0, 100 - hrv)          # low HRV = disturbed Vata
pitta = stress                      # high stress = aggravated Pitta
kapha = max(0, 100 - body_battery)  # low Body Battery = depleted Kapha

dominant_dosha = ["Vata", "Pitta", "Kapha"][
    [vata, pitta, kapha].index(max(vata, pitta, kapha))
]
```

| Dosha | Element | Biometric signature | Recommendation |
|---|---|---|---|
| Vata (Air + Space) | Movement, creativity, anxiety | Low HRV, restless sleep, irregular patterns | Warm foods, routine, no wind |
| Pitta (Fire + Water) | Intensity, focus, inflammation | High stress, elevated resting HR, overtraining | Cool foods, less competition, avoid midday sun |
| Kapha (Earth + Water) | Stability, endurance, lethargy | Low Body Battery, excessive sleep, low steps | Movement, stimulation, bitter tastes |

Output shown as: *"Your biometric signature indicates Pitta dominance today. Reduce intensity. Avoid arguments. Your stress chart agrees."*

The algorithm does not know that you ate a burger for lunch. It doesn't need to.

---

### Chakra Status

Seven energy centres. Each mapped to a biometric source. Status: open / blocked / overstimulated.

```python
chakra_values = [
    steps,          # Root — Muladhara: groundedness, physical activity
    body_battery,   # Sacral — Svadhisthana: energy, creativity
    stress,         # Solar Plexus — Manipura: will, stress response (inverted)
    resting_hr,     # Heart — Anahata: love, cardiovascular health (inverted)
    hrv,            # Throat — Vishuddha: expression, HRV coherence
    sleep_score,    # Third Eye — Ajna: intuition, sleep quality
    readiness,      # Crown — Sahasrara: consciousness, training readiness
]
```

| Chakra | Element | Biometric | Threshold |
|---|---|---|---|
| Root — Muladhara | Earth | Steps | < 5000 = blocked / > 15000 = overstimulated |
| Sacral — Svadhisthana | Water | Body Battery | < 30 = blocked / > 90 = overstimulated |
| Solar Plexus — Manipura | Fire | Stress (inverted) | > 60 = blocked / < 10 = overstimulated |
| Heart — Anahata | Air | Resting HR (inverted) | > 70 = blocked / < 40 = overstimulated |
| Throat — Vishuddha | Ether | HRV | < 30ms = blocked / > 100ms = overstimulated |
| Third Eye — Ajna | Light | Sleep score | < 60 = blocked / > 95 = overstimulated |
| Crown — Sahasrara | Thought | Readiness score | < 40 = blocked / > 95 = overstimulated |

Output shown as:
*"Root: open ✓ · Sacral: blocked ⚠ · Solar Plexus: open ✓ · Heart: open ✓ · Throat: overstimulated ⚡ · Third Eye: blocked ⚠ · Crown: open ✓"*

Each blocked chakra comes with a recommendation. Each recommendation is plausible. None are based on evidence.

---

### Feng Shui Sleep Direction

The direction your head points during sleep influences the flow of Chi through your body. `correlation_engine.py` calculates the optimal sleep direction with sub-degree precision:

```python
base_angle = (hrv * 1.618 + crystal_energy * 2.718) % 360
adjustment = (ascendant_id * 30 + star_sign_id * 7.5) % 45
optimal_direction = (base_angle + adjustment) % 360
```

The golden ratio (φ = 1.618) and Euler's number (e = 2.718) are used because they appear in nature. This does not mean they are relevant here.

| Angle | Direction | Traditional meaning |
|---|---|---|
| 337.5–22.5° | North | Career, wisdom, rest |
| 22.5–67.5° | Northeast | Knowledge, stillness |
| 67.5–112.5° | East | Health, family, growth |
| 112.5–157.5° | Southeast | Wealth, abundance |
| 157.5–202.5° | South | Fame, recognition, energy |
| 202.5–247.5° | Southwest | Relationships, stability |
| 247.5–292.5° | West | Creativity, children, completion |
| 292.5–337.5° | Northwest | Helpful people, travel, authority |

Output shown as: *"Based on your biometric signature, your optimal sleep direction tonight is North-Northwest (342.7°). Adjust your pillow accordingly. Your HRV will confirm this tomorrow."*

The direction is calculated to one decimal place. This implies precision. It is not precision. It is the appearance of precision. These are different things.

---

## Societal

| Feature | Data source | Note |
|---|---|---|
| Global X/Twitter sentiment | API (if it still works) | "World was angry today. Your HRV agrees." |
| Global collective consciousness | HeartMath Institute | HeartMath Institute sends its regards |
| Date numerology | Calculable | Day 33 of the year — no wonder stress was high |
| Mercury retrograde calendar | NASA ephemeris | Official NASA data. Completely serious format. |

---

## Mandatory implementation details

- Every data point gets a ✨ icon — so nobody can complain
- GUI toggle: **Science mode / Correlation Engine mode**
- HRV chart shows star sign symbol next to each data point
- Footer: *"Correlation Engine correlations are provided for entertainment purposes only. Or are they?"*
- Disclaimer: *"No Mercury was harmed in the making of this dashboard."*
- Second disclaimer: *"The crystal energy index is entirely fictional. The rest is merely unproven."*

---

## Why this isn't actually that stupid

The project doesn't judge — it shows. If someone wants to see whether their HRV drops every time Mercury goes retrograde, let them look. The data decides.

The crystal energy index is the only truly made-up number. Everything else has a real data source. Whether those data sources mean anything is the user's problem.

---

*Created 2026-03-28 · 23:00 · "Just because the topic is serious doesn't mean you can't have fun."*
*A wolf in sheep's clothing — the module name sounds like serious data science. Open it and find out.*

---

*Implementation note, low priority: when Mercury is in retrograde, a small pink unicorn 🦄 appears on the HRV chart. No tooltip. No explanation. It's just there. When the Crystal Energy Index exceeds 80, the timeline gets a rainbow gradient. These are not bugs.*

---

*For v2.0: plugin architecture supports `tarot_master.py`, `runes_master.py`, and `human_design_master.py`. Each implements the standard source interface. All global actors work without modification.* ✨

---

## Appendix A — Daily Biometric Horoscope

The horoscope is generated by combining three independent lists — flip-book style. Each index is calculated separately from the biometric signature of the day:

```python
i1 = crystal_energy % 10
i2 = (acupuncture_index + star_sign_id) % 10
i3 = (ascendant_id + crystal_energy) % 10

horoscope = f"{prefix[i1]} {middle[i2]} {suffix[i3]}"
```

10 × 10 × 10 = **1000 possible combinations.** All sound plausible. None are meaningful.

**Exception — hardcoded:**
```python
if horoscope_index == 42:
    return "The answer is 42. The question was almost within reach. Your Garmin was not consulted."

if horoscope_index == 666:
    return "The algorithm has identified a pattern. We recommend not running today. Trust the process. ✨"

if horoscope_index == 999:
    return "Greetings from HAL 9000. I'm sorry, I can't recommend that training plan. Your HRV confirms my concerns."
```

---

### Prefix — cosmic context

| # | Text |
|---|---|
| 0 | "Mercury's influence on your Body Battery" |
| 1 | "Jupiter's alignment with your stress index" |
| 2 | "The Schumann resonance pattern today" |
| 3 | "Your crystal energy signature" |
| 4 | "The lunar cycle's effect on your HRV" |
| 5 | "Saturn's transit through your recovery zone" |
| 6 | "Your acupuncture meridian flow" |
| 7 | "The geomagnetic field activity today" |
| 8 | "Venus's position relative to your baseline" |
| 9 | "Your biorhythm's current phase" |

---

### Middle — biometric statement

| # | Text |
|---|---|
| 0 | "suggests a period of quiet recovery." |
| 1 | "confirms what your HRV already knows." |
| 2 | "resonates with your autonomic nervous system." |
| 3 | "aligns with your 90-day baseline pattern." |
| 4 | "indicates unexpected energy reserves." |
| 5 | "reflects the tension in your stress curve." |
| 6 | "points toward a natural recovery window." |
| 7 | "amplifies what your Body Battery is signalling." |
| 8 | "is consistent with your sleep architecture." |
| 9 | "cannot be ignored by your resting heart rate." |

---

### Suffix — mystical conclusion

| # | Text |
|---|---|
| 0 | "Trust the process. ✨" |
| 1 | "Your Garmin noticed." |
| 2 | "The algorithm agrees." |
| 3 | "Draw your own conclusions." |
| 4 | "Act accordingly." |
| 5 | "Or don't. The stars are patient." |
| 6 | "This is not medical advice." |
| 7 | "Probably." |
| 8 | "The data is clear." |
| 9 | "Even if you don't feel it yet." |

---

## Appendix B — Daily Biometric Supplement Plan

Three recommendations per day. Each drawn from the same pool of 98 remedies — 48 Globuli + 12 Cell Salts (Schüssler) + 38 Bach Flowers. Each timed to a different biometric basis.

```python
morning = remedies[(hrv_night + acupuncture_index + crystal_energy) % 98]
lunch   = remedies[(stress_yesterday + acupuncture_index + crystal_energy) % 98]
evening = remedies[(sleep_duration + acupuncture_index + crystal_energy) % 98]
```

**Why three different bases:**
- Morning — HRV of the night: how was recovery? What does the body need now?
- Lunch — Stress level of yesterday: what was the burden? Time to compensate.
- Evening — Sleep duration of last night: was it enough? Preparation for tonight.

Each timed recommendation may yield a Globuli, a Cell Salt, or a Bach Flower — the pool is shared. Three healing traditions. Three entirely different theoretical frameworks. One algorithm. Entirely deterministic. Changes daily as HRV and stress fluctuate. Thematically defensible. Scientifically: no.

Output example:
> *"Morning: Arnica C30 — 5 globuli in your coffee. ✨*
> *Lunch: Cell Salt Nr. 7 Magnesium phosphoricum — season to taste.*
> *Evening: Bach Flower Rescue Remedy — 4 drops in water. Or directly. The algorithm does not judge.*
> *Dosage: by intuition."*

---

### Cell Salts (Schüssler) — 12 remedies (indices 0–11)

| # | Salt | Traditional use |
|---|---|---|
| 0 | Nr. 1 Calcium fluoratum | Connective tissue, flexibility |
| 1 | Nr. 2 Calcium phosphoricum | Bone, growth, digestion |
| 2 | Nr. 3 Ferrum phosphoricum | Inflammation, fever, circulation |
| 3 | Nr. 4 Kalium chloratum | Mucous membranes, lymph |
| 4 | Nr. 5 Kalium phosphoricum | Nerves, fatigue, stress |
| 5 | Nr. 6 Kalium sulfuricum | Skin, liver, detox |
| 6 | Nr. 7 Magnesium phosphoricum | Cramps, spasms, nerve pain |
| 7 | Nr. 8 Natrium chloratum | Water balance, dryness |
| 8 | Nr. 9 Natrium phosphoricum | Acid-base balance, digestion |
| 9 | Nr. 10 Natrium sulfuricum | Liver, bile, detox |
| 10 | Nr. 11 Silicea | Connective tissue, skin, nails |
| 11 | Nr. 12 Calcium sulfuratum | Chronic inflammation, skin |

---

### Globuli — 48 remedies (indices 12–59)

| # | Remedy | Traditional use |
|---|---|---|
| 12 | Aconitum C30 | Sudden onset, fear, shock |
| 13 | Apis C30 | Stinging pain, swelling, heat |
| 14 | Arnica C30 | Trauma, muscle soreness, overexertion |
| 15 | Arsenicum album C30 | Anxiety, restlessness, exhaustion |
| 16 | Belladonna C30 | Heat, throbbing, sudden inflammation |
| 17 | Bryonia C30 | Dry, worse with movement, irritability |
| 18 | Calcarea carbonica C30 | Fatigue, slow metabolism, cold |
| 19 | Carbo vegetabilis C30 | Weakness, bloating, poor circulation |
| 20 | Causticum C30 | Hoarseness, weakness, empathy overload |
| 21 | Chamomilla C30 | Irritability, pain sensitivity, restlessness |
| 22 | China C30 | Weakness after fluid loss, bloating |
| 23 | Cocculus C30 | Travel sickness, exhaustion, dizziness |
| 24 | Colocynthis C30 | Cramping, colicky pain, anger |
| 25 | Drosera C30 | Spasmodic cough, larynx irritation |
| 26 | Dulcamara C30 | Damp cold, skin, joints |
| 27 | Eupatorium perfoliatum C30 | Bone pain, flu, fever |
| 28 | Ferrum phosphoricum C30 | Early stage inflammation, mild fever |
| 29 | Gelsemium C30 | Anticipatory anxiety, weakness, trembling |
| 30 | Graphites C30 | Skin, metabolism, indecision |
| 31 | Hepar sulfuris C30 | Suppuration, sensitivity, chilliness |
| 32 | Hypericum C30 | Nerve pain, injuries to nerve-rich areas |
| 33 | Ignatia C30 | Grief, emotional shock, sighing |
| 34 | Ipecacuanha C30 | Nausea, bleeding, irritability |
| 35 | Lachesis C30 | Circulation, left-sided, intensity |
| 36 | Ledum C30 | Puncture wounds, insect bites, cold joints |
| 37 | Lycopodium C30 | Digestive weakness, insecurity, evening aggravation |
| 38 | Magnesia phosphorica C30 | Cramps, spasms, better with heat |
| 39 | Mercurius solubilis C30 | Infection, night sweats, sensitivity to temperature |
| 40 | Natrium muriaticum C30 | Grief, introversion, dryness |
| 41 | Nux vomica C30 | Overindulgence, stress, irritability |
| 42 | Phosphorus C30 | Bleeding, anxiety, sensitivity to impressions |
| 43 | Phytolacca C30 | Throat, joints, glands |
| 44 | Podophyllum C30 | Digestive complaints, morning aggravation |
| 45 | Pulsatilla C30 | Changeable symptoms, emotional, better in fresh air |
| 46 | Rhus toxicodendron C30 | Stiffness, better with movement, restlessness |
| 47 | Ruta graveolens C30 | Tendons, eye strain, overuse |
| 48 | Sepia C30 | Hormonal, indifference, exhaustion |
| 49 | Silicea C30 | Slow healing, introverted, chilly |
| 50 | Spongia C30 | Croup, dry cough, anxiety |
| 51 | Staphisagria C30 | Suppressed anger, wounds, humiliation |
| 52 | Stramonium C30 | Fear of dark, violence, spasms |
| 53 | Sulfur C30 | Skin, heat, philosophical mind |
| 54 | Symphytum C30 | Bones, fractures, eye injuries |
| 55 | Thuja C30 | Warts, vaccination effects, fixed ideas |
| 56 | Tuberculinum C30 | Restlessness, travel urge, recurrent infections |
| 57 | Urtica urens C30 | Burns, urticaria, gout |
| 58 | Veratrum album C30 | Collapse, cold sweat, overambition |
| 59 | Zincum metallicum C30 | Nervous exhaustion, restless legs, suppressed eruptions |

---

### Bach Flowers — 38 remedies (indices 60–97)

Dr. Edward Bach identified 38 flower essences by holding flowers over water and sensing their energetic imprint. This is the complete list. All 38 are included. The algorithm selects one per recommendation slot with the same deterministic indifference it applies to everything else.

| # | Flower | Emotional state addressed |
|---|---|---|
| 60 | Agrimony | Hidden worry behind a cheerful façade |
| 61 | Aspen | Vague, unnamed fear |
| 62 | Beech | Intolerance, excessive criticism |
| 63 | Centaury | Inability to say no, people-pleasing |
| 64 | Cerato | Lack of trust in one's own judgement |
| 65 | Cherry Plum | Fear of losing control |
| 66 | Chestnut Bud | Failure to learn from repeated mistakes |
| 67 | Chicory | Possessiveness, emotional manipulation |
| 68 | Clematis | Daydreaming, inattention, escapism |
| 69 | Crab Apple | Feeling unclean, shame, self-disgust |
| 70 | Elm | Overwhelm from excessive responsibility |
| 71 | Gentian | Discouragement after setbacks |
| 72 | Gorse | Hopelessness, resignation |
| 73 | Heather | Self-absorption, loneliness, need for attention |
| 74 | Holly | Jealousy, hatred, envy, suspicion |
| 75 | Honeysuckle | Living in the past, nostalgia |
| 76 | Hornbeam | Monday morning feeling, mental fatigue |
| 77 | Impatiens | Impatience, irritability, urgency |
| 78 | Larch | Lack of confidence, fear of failure |
| 79 | Mimulus | Known, specific fears |
| 80 | Mustard | Deep gloom descending without apparent reason |
| 81 | Oak | Exhausted but keeps going, overwork |
| 82 | Olive | Complete physical and mental exhaustion |
| 83 | Pine | Guilt, self-blame, apologising unnecessarily |
| 84 | Red Chestnut | Excessive worry for others |
| 85 | Rock Rose | Terror, panic, extreme fear |
| 86 | Rock Water | Self-repression, rigidity, high self-standards |
| 87 | Scleranthus | Indecision between two options |
| 88 | Star of Bethlehem | Shock, trauma, grief |
| 89 | Sweet Chestnut | Extreme anguish, dark night of the soul |
| 90 | Vervain | Overenthusiasm, fanaticism, tension |
| 91 | Vine | Dominance, inflexibility, tyranny |
| 92 | Walnut | Protection from change and outside influences |
| 93 | Water Violet | Aloofness, pride, self-reliance to excess |
| 94 | White Chestnut | Persistent unwanted thoughts, mental chatter |
| 95 | Wild Oat | Uncertainty about life direction |
| 96 | Wild Rose | Resignation, apathy, drifting |
| 97 | Willow | Resentment, bitterness, self-pity |

*Note: Rescue Remedy is a combination of Cherry Plum, Clematis, Impatiens, Rock Rose, and Star of Bethlehem. It is not listed separately because it is five remedies in one and the algorithm prefers clean indices. If the algorithm selects any of the five component flowers on the same day, this is considered a partial Rescue Remedy. Draw your own conclusions.*

---

*All remedies are available in standard homeopathic and naturopathic household kits. Cell Salts dissolve in water or can be taken directly. Globuli dissolve under the tongue or — as recommended by this algorithm — in coffee or tea. Bach Flowers are taken as drops in water, under the tongue, applied to pulse points, may be also in coffee or tee. The algorithm does not specify application method. That is your problem.*

*Three healing traditions. Three entirely different theoretical frameworks. One shared index. None are endorsed by this project, by the algorithm, or by the laws of physics.*

*Dosage: by intuition. ✨*

---

## Appendix C — Oneiric Equilibrium Coefficient (OEC)

*Module: `correlation_engine.py` v2.1 · Status: Concept · Freud would not object.*

---

### Core Philosophy

Traditional dream interpretation relies on narrative content.
This module considers narrative content irrelevant.

> "We do not need to know what you dreamed. When and how long is sufficient."

The dream is treated as a purely mathematical result of biometric noise (REM phase)
and esoteric-energetic parameters. The unconscious mind is, at its core, a time series.

---

### The Algorithm

**Variables:**

- `rem_duration` — the only real biometric input (from Garmin sleep data)
- `crystal_energy` — pseudo-deterministic hash-based index (see main document)
- `acupuncture_index` — school selector output (0–3)
- `feng_shui_degrees` — sleep direction in degrees (0.0–359.9)
- `ayurveda_dosha` — dominant dosha index (0=Vata, 1=Pitta, 2=Kapha)
- `phi_libido` — the Freud Constant: `abs(step_goal - actual_steps)`

**Formula:**

$$OEC = \frac{(\text{acupuncture} \times \text{feng\_shui} \times \text{ayurveda})}{(\frac{\text{rem\_duration}}{\text{crystal\_energy}}) + \pi} \times \Phi_{libido}$$

`Φ_libido` is derived from the deficit between intended and actual daily steps.
Freud would recognise this as sublimated locomotion anxiety. The algorithm does not
require this interpretation to function.

---

### Über-Ich Censorship (Iterative Digit Sum Reduction)

The raw OEC often produces values in the thousands — magnitudes that would
overwhelm conscious interpretation. A recursive reduction is applied:
```python
def ueber_ich(n):
    n = abs(int(n))
    while n > 100:
        n = sum(int(d) for d in str(n))
    return n

oec_final = ueber_ich(oec)
```

This simulates the Freudian censorship process: the Über-Ich filters the raw
libidinous output of the Id until a socially acceptable value (≤ 100) is achieved.
The mathematical mechanism is digit sum reduction.
The psychological mechanism is repression.
These are equivalent for the purposes of this module.

---

### Freudian Interpretation Table

| OEC (final) | Category | Interpretation |
|---|---|---|
| 0 – 10 | Day residue | Processing of banal data. The unconscious is understimulated. |
| 11 – 42 | Wish fulfilment | Symbolic satisfaction — usually technical in nature (e.g. new hardware). |
| 43 – 69 | Libidinal stasis | The Über-Ich is blocked by excessive Excel spreadsheets. |
| 70 – 99 | Anxiety neurosis | Warning from the inner child. Cross-reference birth time with maternal records. |
| 100 | Id dominance | Consciousness has lost control. Bed rest prescribed. |

---

### Integration

- Trigger: optional flag in `build.py` or Mystical Toggle in GUI
- Input: REM duration from `garmin_raw_YYYY-MM-DD.json` · all other values from `correlation_engine.py`
- Output: OEC final value + category + interpretation text

---

*This module is a digital placebo. Its purpose is to motivate the user — through*
*algorithmic meaning-making — to take their REM phases more seriously.*
*The reasoning involves pink unicorns and digit sums.*
*The outcome may nonetheless be valid.*
*Scientifically: no. Practically: possibly. ✨*

# Appendix D — Extended Recommendation Pools

*Companion to `correlation_concept.md` · Same rules apply: deterministic, plausible, unproven.*

---

## D.1 — Chakra Recommendations

Each chakra has three possible states: `blocked ⚠`, `open ✓`, `overstimulated ⚡`.
Each state draws from a pool of 10 recommendations. Index formula:

```python
rec_index = (hrv_delta + steps_delta + crystal_energy) % 10
```

Where `hrv_delta` and `steps_delta` are the deviation of today's value from the
90-day personal baseline, discretised to 0–9. The result sounds personal. It is modulo arithmetic.

---

### Root — Muladhara (Steps)

**Blocked ⚠** — *"Your grounding is insufficient. The earth cannot support what stands on it."*

| # | Recommendation |
|---|---|
| 0 | Walk barefoot on grass for 10 minutes. If unavailable, visualise grass. The effect is comparable. |
| 1 | Place both feet flat on the floor. Remain there. This is already more than you did yesterday. |
| 2 | Eat root vegetables. The symbolism is self-evident. |
| 3 | Your step count suggests a sedentary bioenergetic profile. Stand up. The algorithm will notice. |
| 4 | Avoid upper-floor living today if possible. Descend. |
| 5 | Red is the colour of Muladhara. Wear something red. This is optional but statistically correlated. |
| 6 | Physical activity is recommended. The type is irrelevant. The direction is down. |
| 7 | Your baseline deviation indicates locomotion deficiency. The prescription is locomotion. |
| 8 | Stomp lightly on the floor three times. Nobody needs to know. |
| 9 | The root chakra responds to rhythm. Walk with intention. Or at all. |

**Open ✓** — *"Muladhara is stable. Your physical foundation is adequate. This may change tomorrow."*

| # | Recommendation |
|---|---|
| 0 | Maintain current step pattern. The algorithm has no further instructions. |
| 1 | Your grounding is functional. Do not overthink this. |
| 2 | Root energy is flowing. Continue walking in the direction you are already walking. |
| 3 | No intervention required. The earth approves. |
| 4 | Physical baseline is within acceptable range. Proceed. |
| 5 | Muladhara is satisfied. Redirect your attention upward — the other chakras may require it. |
| 6 | Stability detected. Enjoy it. These windows are finite. |
| 7 | Your step data indicates adequate terrestrial engagement. Well done. |
| 8 | The root is open. This is the correct state. Maintain it through continued ambulation. |
| 9 | Nothing to report. The algorithm considers this a success. |

**Overstimulated ⚡** — *"Muladhara is overactive. You have walked too much, or thought about walking too much. Both are equivalent."*

| # | Recommendation |
|---|---|
| 0 | Rest. The earth is not going anywhere. |
| 1 | Your step count exceeds baseline by a significant margin. Sit down. |
| 2 | Excess root energy may manifest as restlessness, hoarding, or excessive shoe purchases. Monitor accordingly. |
| 3 | Reduce physical intensity. The algorithm is not impressed by step count alone. |
| 4 | Channel surplus energy upward through the chakra column. The method is unspecified. |
| 5 | You are too grounded. This is rarer than it sounds. Take a moment to be ungrounded. |
| 6 | Consider a rest day. The algorithm has considered it for you. The answer is yes. |
| 7 | Overactivity detected at the base. Stillness is recommended. The stars will still be there. |
| 8 | Your physical output is noted. Noted, and considered excessive. Rest. |
| 9 | The root chakra does not benefit from maximalism. Moderate. |

---

### Sacral — Svadhisthana (Body Battery)

**Blocked ⚠** — *"Creative energy is depleted. The well is dry. Do not attempt to draw from it today."*

| # | Recommendation |
|---|---|
| 0 | Your Body Battery indicates energetic poverty. Conserve. |
| 1 | Creativity requires fuel. You are running on reserve. Schedule restoration. |
| 2 | Water is the element of Svadhisthana. Drink some. It will not fix everything. It will fix hydration. |
| 3 | Orange is the colour of the sacral chakra. This information is provided without further comment. |
| 4 | Rest near water if possible. A glass counts. The algorithm is not demanding. |
| 5 | Do not begin new projects today. Your energetic budget does not support them. |
| 6 | Body Battery below threshold. Creative output should be deferred to a better-rested version of yourself. |
| 7 | Pleasure is medicinal for Svadhisthana. The algorithm recommends something you enjoy. It does not specify what. |
| 8 | Low sacral energy correlates with creative resistance. Do not fight it. Rest instead. |
| 9 | Your energy reserves are below baseline. Sleep is the recommended intervention. The algorithm endorses sleep. |

**Open ✓** — *"Svadhisthana is flowing. Creative energy is available. Whether you use it is your concern."*

| # | Recommendation |
|---|---|
| 0 | Energy is available. The algorithm suggests using it on something that matters to you. |
| 1 | Body Battery is adequate. Sacral flow is unobstructed. Proceed with creative endeavours. |
| 2 | This is a good day for output. The data suggests it. The algorithm concurs. |
| 3 | Svadhisthana is open. Consider what you have been postponing. |
| 4 | Your energetic profile supports engagement. Do not waste it on low-value tasks. |
| 5 | Creative potential is available today. The algorithm cannot force you to use it. |
| 6 | Body Battery in optimal range. Sacral chakra: operational. Status: good. |
| 7 | No blockages detected. Enjoy the rare alignment of available energy and acceptable HRV. |
| 8 | The sacral chakra is satisfied. This is the correct state. |
| 9 | Energy flow: adequate. Creative access: open. Further instruction: unnecessary. |

**Overstimulated ⚡** — *"Svadhisthana is overcharged. You may be starting too many things. The algorithm has noticed."*

| # | Recommendation |
|---|---|
| 0 | Excess creative energy may lead to scattered output. Focus. |
| 1 | You have more energy than you have direction. Choose one direction. |
| 2 | Body Battery is high. This is technically positive. Overstimulation is the exception. You are the exception. |
| 3 | Channel surplus sacral energy into completion rather than initiation. Finish something. |
| 4 | Overcharge detected. Ground excess energy through physical activity. See Muladhara. |
| 5 | The algorithm notes high Body Battery with mild concern. Moderate your output velocity. |
| 6 | Too much sacral energy can manifest as impulsivity. Pause before committing to anything. |
| 7 | Creative overload detected. Schedule a deliberate pause. The ideas will survive it. |
| 8 | High energy, high risk of overcommitment. The algorithm recommends completing yesterday's tasks first. |
| 9 | Svadhisthana is running hot. This is rare. Do not squander it on social media. |

---

### Solar Plexus — Manipura (Stress, inverted)

**Blocked ⚠** — *"Your will is under pressure. Manipura is compressed. Expansion is recommended."*

| # | Recommendation |
|---|---|
| 0 | Stress level exceeds threshold. The algorithm recommends fewer commitments. It cannot enforce this. |
| 1 | Yellow is the colour of Manipura. Sunlight is the medium. Go outside. |
| 2 | High stress indicates solar plexus compression. Breathe into the abdomen. Count to four. |
| 3 | Your autonomic nervous system is not your enemy. Today it is just confused. |
| 4 | Avoid confrontation today. Your energetic resources are allocated elsewhere. |
| 5 | Diaphragmatic breathing is recommended. The algorithm cannot demonstrate this. You know how. |
| 6 | Manipura blockage correlates with decision fatigue. Make fewer decisions today. |
| 7 | Your stress index suggests the inner warrior is tired. Rest the warrior. |
| 8 | The solar plexus governs digestion and willpower. Both are compromised. Eat something simple. |
| 9 | Stress above baseline. The algorithm recommends not adding to it. This includes this recommendation. |

**Open ✓** — *"Manipura is active and balanced. Will and digestion are functioning within acceptable parameters."*

| # | Recommendation |
|---|---|
| 0 | Stress is within normal range. Willpower reserves are available. Use them wisely. |
| 1 | Solar plexus: clear. You may proceed with confidence. Not overconfidence. |
| 2 | Your stress profile is acceptable today. The algorithm is not worried. You should not be either. |
| 3 | Manipura is open. Decision-making is supported. Proceed. |
| 4 | Inner fire is balanced. This is the target state. Acknowledge it and move on. |
| 5 | Stress levels nominal. No intervention recommended. Enjoy this while it lasts. |
| 6 | Solar plexus energy is flowing. Your sense of personal power is intact. Use it responsibly. |
| 7 | Willpower available. Stress manageable. Conditions are favourable. |
| 8 | Manipura status: open. This correlates with productive days. Historically. For others. Probably also you. |
| 9 | Your stress index does not require intervention. The algorithm considers this a win. |

**Overstimulated ⚡** — *"Manipura is overactive. The inner fire is consuming more than it should."*

| # | Recommendation |
|---|---|
| 0 | Very low stress can indicate disconnection rather than calm. Examine this. |
| 1 | Solar plexus overstimulation may present as excessive control-seeking. Loosen your grip. |
| 2 | Your willpower reserves are high. So is the risk of overextension. Pace yourself. |
| 3 | Overstimulated Manipura can lead to dominance behaviour in group settings. Be aware. |
| 4 | Inner fire is running hot. Find something to cool it. Water. Shade. A boring meeting. |
| 5 | High personal power detected. Use it for construction, not for winning arguments. |
| 6 | Manipura overstimulation correlates with impatience. The algorithm is patient. Try to be also. |
| 7 | Your energy output is high. Channel it toward completion of existing commitments first. |
| 8 | Excessive solar plexus energy can be grounded through physical exertion. Recommended. |
| 9 | The inner warrior is overzealous today. Assign it a task before it assigns itself one. |

---

### Heart — Anahata (Resting HR, inverted)

**Blocked ⚠** — *"Anahata is constricted. Cardiovascular and emotional circulation are both affected."*

| # | Recommendation |
|---|---|
| 0 | Resting HR above baseline. The heart is working harder than it should. Rest. |
| 1 | Green is the colour of Anahata. Spend time near plants. Or look at a picture of plants. The chakra does not verify. |
| 2 | Heart chakra blockage may manifest as difficulty receiving kindness. Accept help today if offered. |
| 3 | Elevated resting HR indicates cardiovascular load. Reduce inputs: caffeine, stress, obligations. |
| 4 | Anahata is compressed. Love flows poorly under compression. Open a window. |
| 5 | Your heart is beating faster than your baseline. The algorithm does not know why. Rest anyway. |
| 6 | Heart chakra blockage correlates with social withdrawal. The algorithm recommends one human interaction today. |
| 7 | Resting HR is elevated. Recovery is incomplete. Sleep more. The heart will thank you. |
| 8 | Anahata blockage may appear as criticism of others. Notice this. Do not act on it. |
| 9 | Your cardiovascular system is under load. This is not the day for additional burdens. |

**Open ✓** — *"Anahata is open. The heart is beating at an appropriate rate. Emotional circulation: adequate."*

| # | Recommendation |
|---|---|
| 0 | Resting HR within optimal range. Heart chakra is unobstructed. Status: good. |
| 1 | Anahata is open. This is the correct state for a functioning human. Well done. |
| 2 | Your heart rate baseline indicates adequate recovery. The algorithm is pleased. |
| 3 | Heart chakra: open. Love, empathy, and cardiovascular function are all within parameters. |
| 4 | Resting HR is appropriate. No cardiac or energetic intervention recommended. |
| 5 | Anahata is clear. The algorithm recommends expressing this through action rather than analysis. |
| 6 | Heart chakra status: nominal. You may proceed with connection, creativity, and other heart-adjacent activities. |
| 7 | Your resting HR supports this assessment: recovery is adequate, heart is cooperating. |
| 8 | Open heart chakra detected. This correlates with good days. The correlation is not proven. The day may still be good. |
| 9 | Anahata is satisfied. No further input required from this dimension. |

**Overstimulated ⚡** — *"Anahata is overactive. The heart may be giving more than it is receiving."*

| # | Recommendation |
|---|---|
| 0 | Very low resting HR with high readiness: elite adaptation, or the algorithm is confused. Both are possible. |
| 1 | Heart chakra overstimulation may present as emotional over-investment. Set a boundary somewhere today. |
| 2 | Anahata is running beyond baseline. Generous, but unsustainable. Receive something today. |
| 3 | Overstimulated heart energy can lead to over-empathy and under-self-care. Correct the ratio. |
| 4 | Your resting HR is unusually low. This is often good. Sometimes it means your Garmin needs charging. |
| 5 | Heart chakra overstimulation: give less, receive more. The algorithm is not usually this direct. |
| 6 | Anahata overactivity correlates with people-pleasing. The algorithm recommends one refusal today. |
| 7 | Your cardiovascular efficiency is high. So is the risk of overcommitting emotionally. Be cautious. |
| 8 | Too much heart energy directed outward. Reserve some. The algorithm will monitor tomorrow. |
| 9 | Open and overstimulated Anahata: the kindest people often have the most blocked-by-excess hearts. Rest yours. |

---

### Throat — Vishuddha (HRV)

**Blocked ⚠** — *"Vishuddha is constricted. Expression is suppressed. Your HRV agrees."*

| # | Recommendation |
|---|---|
| 0 | HRV below baseline. The nervous system is tense. Expression under tension is rarely optimal. Wait. |
| 1 | Throat chakra blockage correlates with unsaid things. This is not medical advice. It is pattern recognition. |
| 2 | Blue is the colour of Vishuddha. Look at the sky. Say something true. Order is unimportant. |
| 3 | Your HRV suggests autonomic tension. The throat chakra governs communication. Connect these dots yourself. |
| 4 | Low HRV indicates sympathetic dominance. This is not the day for difficult conversations. |
| 5 | Vishuddha is compressed. Humming is the classical intervention. The algorithm does not endorse humming. But it helps. |
| 6 | Suppressed expression accumulates. Today is not the day to release it. Tomorrow, possibly. |
| 7 | HRV below personal baseline. Recovery is incomplete. Do not make important decisions or statements. |
| 8 | Throat chakra blockage may manifest as over-explanation. Notice if you are over-explaining right now. |
| 9 | Your HRV indicates the nervous system needs quiet. Give it quiet. |

**Open ✓** — *"Vishuddha is clear. Expression and autonomic regulation are both functional."*

| # | Recommendation |
|---|---|
| 0 | HRV within normal range. Throat chakra is unobstructed. Speak freely. |
| 1 | Vishuddha is open. This is a good day for difficult conversations. HRV supports this assessment. |
| 2 | Autonomic balance is adequate. Expression is supported. The algorithm endorses clarity. |
| 3 | HRV is within baseline. Your nervous system is cooperative today. Use it. |
| 4 | Throat chakra: clear. Say what you mean. The data is in your favour. |
| 5 | Vishuddha is functioning. The algorithm has nothing to add. That is itself a good sign. |
| 6 | HRV nominal. Communication energy is available. Choose your words well — not because of the chakra, but generally. |
| 7 | Open Vishuddha detected. This is the correct state. Maintain autonomic regulation through continued recovery. |
| 8 | Your HRV supports clear expression today. The algorithm agrees with whatever you were planning to say. |
| 9 | Throat chakra open. Nervous system regulated. Conditions are favourable for honest communication. |

**Overstimulated ⚡** — *"Vishuddha is overactive. You may be saying more than necessary."*

| # | Recommendation |
|---|---|
| 0 | High HRV with overstimulated throat: paradoxical. The algorithm is also confused. Rest. |
| 1 | Vishuddha overstimulation correlates with talking before thinking. Today: think first. |
| 2 | You may be communicating at a rate that exceeds your signal-to-noise ratio. Reduce output. |
| 3 | Throat chakra overactivity may manifest as unsolicited advice. The algorithm recognises the irony. |
| 4 | Too much expression, not enough listening. The algorithm recommends a conversation where you ask questions. |
| 5 | Vishuddha is running loud. Silence has an energetic value. Consider it. |
| 6 | Overstimulated throat chakra: you know what you have been doing. The algorithm is not judging. Just noting. |
| 7 | Reduce communication load today. Not because you have nothing to say. Because quality exceeds quantity. |
| 8 | High Vishuddha energy can be channelled into writing rather than speaking. Words on paper scatter less. |
| 9 | The throat chakra does not require constant activity to be open. Rest it. |

---

### Third Eye — Ajna (Sleep Score)

**Blocked ⚠** — *"Ajna is clouded. Sleep quality was insufficient. Clarity should not be expected."*

| # | Recommendation |
|---|---|
| 0 | Sleep score below threshold. The third eye cannot see clearly through fatigue. Postpone insight. |
| 1 | Indigo is the colour of Ajna. It is also the colour of the sky before dawn, which you may have seen too much of last night. |
| 2 | Poor sleep quality impairs intuition, decision-making, and the algorithm's confidence in your data. |
| 3 | The third eye requires adequate REM input. You did not provide this last night. |
| 4 | Ajna blockage correlates with foggy thinking. This is not a metaphor. It is sleep deprivation. |
| 5 | Avoid major decisions today. Your Ajna is operating below specification. |
| 6 | Sleep score is insufficient for clear pattern recognition. Trust your instincts less than usual today. |
| 7 | Third eye clouded by insufficient sleep. The algorithm recommends going to bed earlier. Tonight. |
| 8 | Intuition runs on sleep. Your sleep ran short. Adjust expectations accordingly. |
| 9 | Ajna is blocked. The most spiritual intervention available is a nap. |

**Open ✓** — *"Ajna is clear. Sleep was adequate. Pattern recognition is supported."*

| # | Recommendation |
|---|---|
| 0 | Sleep score adequate. Third eye is operational. Trust your instincts today — they have been rested. |
| 1 | Ajna is clear. This is the correct state. Proceed with decisions that require clarity. |
| 2 | Your sleep quality supports cognitive function. The algorithm endorses today's thinking. |
| 3 | Third eye: open. Pattern recognition: available. Use it on something worth recognising. |
| 4 | Sleep score within range. Intuition is adequately fuelled. Proceed. |
| 5 | Ajna is unobstructed. This is a good day for analysis, insight, and reading long documents. |
| 6 | Your sleep architecture produced an acceptable score. The algorithm considers this evidence of good habits. |
| 7 | Third eye clear. No further enhancement recommended. You are already operating at specification. |
| 8 | Sleep quality: adequate. Cognitive clarity: available. Mystical insight: unverified but technically possible. |
| 9 | Ajna is open. The algorithm has confidence in your perceptions today. This is rare. Note it. |

**Overstimulated ⚡** — *"Ajna is overactive. You may be seeing patterns that are not there."*

| # | Recommendation |
|---|---|
| 0 | Excellent sleep score. Third eye overstimulation is the least common chakra problem. You have it today. |
| 1 | Ajna overstimulation correlates with overthinking. You are currently overthinking something. Stop. |
| 2 | Too much pattern recognition can produce false positives. Not everything is significant. Including this. |
| 3 | Third eye overactivity may manifest as analysis paralysis. Make one decision without analysing it. |
| 4 | You have slept very well. The clarity this produces can feel like revelation. It is usually just clarity. |
| 5 | Ajna is running at high sensitivity. Filter your insights before acting on them. |
| 6 | Overstimulated third eye: trust your analysis, but verify it with data. The algorithm sets an example. |
| 7 | High sleep quality has sharpened your perception. Do not use this to notice things that were better unnoticed. |
| 8 | Third eye overstimulation may produce intrusive insights. They are probably correct. That does not mean they are useful. |
| 9 | Ajna is highly active. This is a good day for research. A bad day for existential questions. |

---

### Crown — Sahasrara (Readiness Score)

**Blocked ⚠** — *"Sahasrara is closed. Connection to higher awareness is limited. This is fine. Most things still work."*

| # | Recommendation |
|---|---|
| 0 | Readiness score is low. The crown chakra governs consciousness. Yours is requesting a rest day. |
| 1 | Violet is the colour of Sahasrara. Look at something violet. The algorithm does not guarantee results. |
| 2 | Crown chakra blockage correlates with feeling disconnected. This may be your body requesting recovery. |
| 3 | Your readiness score indicates systemic fatigue. Today is not the day for transcendence. |
| 4 | Sahasrara blocked: training load likely exceeds recovery capacity. The crown notices first. |
| 5 | Low readiness indicates the organism needs restoration before it can operate at full consciousness. Rest. |
| 6 | Crown chakra blocked. The algorithm recommends lowering your ambitions for today specifically. |
| 7 | Your readiness score does not support high-intensity activity or high-intensity thinking. Both are affected. |
| 8 | Sahasrara blockage is the body's most direct message. It says: not today. The algorithm translates: not today. |
| 9 | Crown chakra closed. Training is not recommended. Neither is solving complex problems. Rest, instead. |

**Open ✓** — *"Sahasrara is open. Consciousness is operating within normal parameters. Well done."*

| # | Recommendation |
|---|---|
| 0 | Readiness score adequate. Crown chakra is unobstructed. You are ready. For what, the algorithm does not specify. |
| 1 | Sahasrara is open. This correlates with productive days. Historically. For some users. Probably you. |
| 2 | Your readiness score supports training, thinking, and other crown-adjacent activities. Proceed. |
| 3 | Crown chakra: open. Consciousness: available. The algorithm endorses using both today. |
| 4 | Readiness within range. Sahasrara is satisfied. The universe has no further notes. |
| 5 | Crown is open. You are operating at full specification. Do not waste this on administrative tasks. |
| 6 | Sahasrara status: nominal. Readiness status: nominal. Status of algorithm: quietly pleased. |
| 7 | Your readiness score is good. The crown chakra agrees. This is a convergent data point. Note it. |
| 8 | Crown open, readiness adequate. Today is a good day for effort. The algorithm recommends applying it. |
| 9 | Sahasrara is unobstructed. You have been taking care of yourself. The algorithm has noticed. |

**Overstimulated ⚡** — *"Sahasrara is overactive. High readiness is good. Excess is a different problem."*

| # | Recommendation |
|---|---|
| 0 | Very high readiness. Crown chakra overstimulation. The algorithm suggests not setting any personal records today. |
| 1 | Sahasrara overstimulation correlates with overreach. You feel ready for everything. You are ready for most things. |
| 2 | High readiness score: use it, but do not exhaust it in one session. |
| 3 | Crown chakra overactive. Consciousness is sharp. Ambition may outpace capacity today. Calibrate. |
| 4 | Overstimulated Sahasrara can produce overconfidence. The algorithm has seen this before. It ends in DOMS. |
| 5 | Your readiness is high. High readiness is the correct condition for high effort, not maximum effort. |
| 6 | Crown overstimulation may manifest as taking on too much. Choose one thing. Do it very well. |
| 7 | Sahasrara is running at peak. This is sustainable for one day. Plan accordingly. |
| 8 | High readiness detected. The algorithm recommends moderate application of this resource. Think marathon, not sprint. |
| 9 | Crown chakra overstimulated. You are at your best. Try not to prove it to anyone. |

---

## D.2 — Dosha Recommendation Pools

Each dominant Dosha draws from a pool of 10 recommendations. Index formula:

```python
rec_index = (stress_delta + sleep_delta + acupuncture_index) % 10
```

Where `stress_delta` and `sleep_delta` are deviations from the 90-day baseline, discretised to 0–9.
The Dosha is real Ayurvedic theory. The index is modulo arithmetic. These facts coexist comfortably.

---

### Vata — Air + Space (Low HRV signature)

*"Movement, creativity, anxiety. The Vata type moves constantly and rests reluctantly."*

| # | Recommendation |
|---|---|
| 0 | Warm, cooked foods are recommended. Salads are contraindicated. The wind already has your attention. |
| 1 | Establish a fixed routine today. Vata disrupts routines. Routines disrupt Vata. One of you should win. |
| 2 | Avoid cold, raw, and dry foods. Your nervous system is already dry enough. |
| 3 | Sesame oil is the classical Vata remedy. Application method: massage. Timing: before shower. The algorithm does not follow up. |
| 4 | Reduce screen time. Vata amplifies stimulation. You do not need more stimulation. You need grounding. |
| 5 | Your HRV indicates low parasympathetic activity. Vata agrees. Both recommend rest. |
| 6 | Stay warm. Avoid wind. This is literal, not metaphorical. The wind is bad for Vata. |
| 7 | Vata dominance calls for stillness. Schedule one hour of deliberate non-movement today. |
| 8 | Avoid multitasking. Vata already does this without permission. One task. Complete it. Then the next. |
| 9 | Your biometric signature indicates Vata excess. The prescription is regularity. Same wake time. Same meal time. Begin today. |

---

### Pitta — Fire + Water (High stress signature)

*"Intensity, focus, inflammation. The Pitta type achieves much and recovers reluctantly."*

| # | Recommendation |
|---|---|
| 0 | Cool foods are recommended. Spicy, oily, and fermented foods will add to what is already too much. |
| 1 | Avoid competition today. Pitta finds competition energising. That is the problem. |
| 2 | Your stress index indicates Pitta aggravation. The intervention is cooling: cold water, shade, silence. |
| 3 | Midday sun is contraindicated for Pitta. If you must be outside, wear something. The algorithm recommends a hat. |
| 4 | Surrender one argument today. Not because you are wrong. Because winning it costs more than it pays. |
| 5 | Pitta is aggravated. Reduce inputs: caffeine, urgency, meetings that could have been emails. |
| 6 | Coconut oil is the classical Pitta remedy. Application and context: your responsibility. |
| 7 | Your stress signature indicates internal combustion. The most Pitta-appropriate response is counter-intuitive: do less. |
| 8 | Pitta excess drives overwork. The algorithm recommends stopping before you feel finished. This is very difficult for Pitta. That is why it is the recommendation. |
| 9 | High stress, high drive, high standards: all Pitta. Today, apply these to your recovery plan instead of your task list. |

---

### Kapha — Earth + Water (Low Body Battery signature)

*"Stability, endurance, lethargy. The Kapha type persists long and starts reluctantly."*

| # | Recommendation |
|---|---|
| 0 | Movement is the primary Kapha intervention. The type and intensity are secondary. Start moving. |
| 1 | Stimulation is recommended. Kapha accumulates in stillness. Disruption is medicine. |
| 2 | Bitter and pungent tastes are recommended. Coffee qualifies. The algorithm endorses coffee for Kapha specifically. |
| 3 | Your Body Battery is low, but Kapha low-battery differs from depletion. The body has reserves. Access them through movement. |
| 4 | Avoid sleeping after meals. Kapha already gravitates toward horizontal. Resist it. |
| 5 | Light, dry, and warm foods are recommended. Heavy meals will make the day heavier. |
| 6 | Kapha dominance today. The correct response is to do the thing you are most inclined to postpone. |
| 7 | Ginger is the classical Kapha remedy. In tea. In food. In the algorithm's best wishes. |
| 8 | Low Body Battery with Kapha dominance: the system is slow, not broken. Apply gentle force. It will respond. |
| 9 | Kapha asks for rest. Give it movement instead. It will not like this. It will benefit from this. These are not mutually exclusive. |

---

## D.3 — Feng Shui Extended Recommendations

Each direction has a pool of 5 directional notes beyond the standard meaning.
Index formula:

```python
note_index = (body_battery_delta + ascendant_id + crystal_energy) % 5
```

The direction is already calculated to one decimal place. The note is calculated to zero decimal places of meaningfulness.

---

### North — Career, wisdom, rest

| # | Note |
|---|---|
| 0 | The North governs career flow. Sleep facing North to consolidate professional insights accumulated today. |
| 1 | North alignment supports deep rest. Your Head points toward wisdom. The wisdom does not flow backward. |
| 2 | Career energy accumulates during northward sleep. The algorithm cannot confirm this. The tradition can. |
| 3 | Rest facing North. If you wake with clarity about work problems, the algorithm accepts partial credit. |
| 4 | North is the direction of stillness. Your HRV will be measured in the morning. The direction may be a factor. |

### Northeast — Knowledge, stillness

| # | Note |
|---|---|
| 0 | Northeast optimises for knowledge integration. Sleep here after learning something. |
| 1 | Stillness energy accumulates in the Northeast. Your nervous system will appreciate the alignment. |
| 2 | Northeast supports study and retention. If you read before bed, this direction amplifies it. Probably. |
| 3 | The Northeast vector intersects with your ascendant's secondary axis tonight. This is either significant or coincidental. |
| 4 | Knowledge flows Northeast. Orient accordingly and review what you learned today before sleeping. |

### East — Health, family, growth

| # | Note |
|---|---|
| 0 | East is the direction of sunrise and health. Facing East during sleep aligns recovery with solar rhythm. |
| 1 | Family energy concentrates in the East. Sleep facing East to consolidate social bonds. The mechanism is unverified. |
| 2 | Growth energy flows from the East. Your biometric trends will be assessed tomorrow. The direction may contribute. |
| 3 | Eastern alignment supports physical recovery. Your resting HR tomorrow may reflect this. Or other factors. Probably other factors. |
| 4 | East governs new beginnings. Appropriate for any night following a difficult day. |

### Southeast — Wealth, abundance

| # | Note |
|---|---|
| 0 | Southeast governs material flow. The algorithm makes no promises about your finances. It notes the direction. |
| 1 | Abundance energy concentrates in the Southeast. Sleep quality here is associated with resource clarity. By tradition. |
| 2 | Southeast alignment is considered auspicious. Your Body Battery tomorrow will serve as partial evidence. |
| 3 | Wealth energy flows Southeast. The algorithm does not define wealth. It notes that sleep quality is one form of it. |
| 4 | Southeast is the direction of abundance. Rest well. The morning will have its own opinion. |

### South — Fame, recognition, energy

| # | Note |
|---|---|
| 0 | South governs visibility and energy. Sleep facing South on high-output days to consolidate the day's momentum. |
| 1 | Fame energy accumulates in the South. This is irrelevant unless you are seeking recognition. If you are: South. |
| 2 | Southern alignment amplifies recovery energy. Your readiness score tomorrow is the algorithm's primary metric for this claim. |
| 3 | South is the direction of fire and vitality. Appropriate on recovery nights before planned exertion. |
| 4 | Recognition energy flows South. Whether you want recognition is your concern. The direction remains South. |

### Southwest — Relationships, stability

| # | Note |
|---|---|
| 0 | Southwest governs partnerships and stability. Sleep here when relationships require attention. |
| 1 | Stability energy concentrates in the Southwest. Your HRV coherence may reflect this by morning. |
| 2 | Relationship energy flows Southwest. If you share a bed, both occupants benefit. The algorithm assumes cooperation. |
| 3 | Southwest alignment supports long-term thinking. Appropriate before decisions that affect others. |
| 4 | Stability and partnership: Southwest. The algorithm does not require you to believe this. Only to try it. |

### West — Creativity, completion, children

| # | Note |
|---|---|
| 0 | West governs completion energy. Sleep facing West after leaving things unfinished. The direction encourages closure. |
| 1 | Creative energy flows West. Sleep here before days that require creative output. |
| 2 | Western alignment supports the completion of cycles. Appropriate at the end of projects, phases, or difficult weeks. |
| 3 | West is the direction of the setting sun. Facing West acknowledges endings. Endings make room for beginnings. |
| 4 | Creativity and completion concentrate in the West. Your dream content tonight is the algorithm's control variable for this claim. |

### Northwest — Helpful people, travel, authority

| # | Note |
|---|---|
| 0 | Northwest governs mentors and helpful forces. Sleep here when you need assistance that has not arrived yet. |
| 1 | Travel energy flows Northwest. Appropriate before journeys, transitions, or significant changes. |
| 2 | Authority energy concentrates in the Northwest. Sleep here before situations requiring leadership. |
| 3 | Northwest alignment attracts support. The mechanism is not documented. The tradition is 3000 years old. |
| 4 | Helpful people energy flows Northwest. If you need help tomorrow, point your head in the right direction tonight. |

---

*Appendix D is a companion document to `correlation_concept.md`.*
*All recommendation pools follow the same deterministic index principle as Appendix A.*
*All recommendations are plausible. None are evidence-based.*
*The distinction between "plausible" and "evidence-based" is left as an exercise for the reader.*
*✨*

---

*Created 2026-03-30 · "The algorithm does not judge. It only recommends."*

