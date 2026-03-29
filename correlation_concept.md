![Garmin Local Archive](screenshots/Banner.png)

# Garmin Local Archive — Correlation Engine ✨

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

And honestly: if the Reddit critic writes "this project correlates HRV with star signs and crystal energy" — forty people will clone it because of that.

Best organic marketing ever. ✨

---

## What the critic will say

> "They added astrology and made-up crystal energy to a health data tool. This is what happens when AI writes your code."

What he won't say: he checked if the Schumann resonance data source was real. It is.

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

