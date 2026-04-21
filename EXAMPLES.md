# Use Cases & Examples — meteoswiss-mcp

### 🏫 Bildung & Schule
Lehrpersonen, Schulbehörden, Fachreferent:innen

**Planung eines Sporttags**
«Welche Tage eignen sich nächste Woche für einen Sporttag in Zürich?»
→ `meteo_school_check(location="Zürich", activity="Sporttag")`
Warum nützlich: Liefert eine schnelle 🟢/🟡/🔴-Einschätzung für jeden Tag direkt aus dem hochaufgelösten ICON-Modell, was die organisatorische Planung massiv vereinfacht.

**Wetterbedingungen für eine Exkursion prüfen**
«Wie wird das Wetter beim Schulhaus Leutschenbach am Freitag, und wie hoch ist der UV-Index?»
→ `meteo_forecast(location="Zürich Oerlikon", days=5)`
Warum nützlich: Erlaubt es Lehrpersonen, den Ausflug präzise vorzubereiten und rechtzeitig an Sonnenschutz oder wetterfeste Kleidung zu erinnern.

### 👨‍👩‍👧 Eltern & Schulgemeinde
Elternräte, interessierte Erziehungsberechtigte

**Entscheidung über den Schulweg**
«Ist es heute Morgen in Bern zu nass oder zu kalt, um mit dem Velo zur Schule zu fahren?»
→ `meteo_current(station="BER")`
Warum nützlich: Bietet Eltern sofortige, lokale Echtzeitdaten (inklusive 10-Minuten-Niederschlagswerten), um den sichersten und angenehmsten Schulweg für ihr Kind zu wählen.

**Wettergefahren für den Nachmittag**
«Gibt es aktuell Wetterwarnungen für den Kanton Bern, die den Nachmittagsunterricht im Freien betreffen?»
→ `meteo_warnings(canton="BE")`
Warum nützlich: Hilft Eltern und Schulgemeinden, sich proaktiv auf potenzielle wetterbedingte Einschränkungen oder Gefahren einzustellen.

### 🗳️ Bevölkerung & öffentliches Interesse
Allgemeine Öffentlichkeit, politisch und gesellschaftlich Interessierte

**Klimavergleich zwischen Regionen**
«Ist Lugano wirklich deutlich sonniger als Zürich? Zeig mir die Jahreswerte.»
→ `meteo_climate_normals(station="LUG")`
→ `meteo_climate_normals(station="SMA")`
Warum nützlich: Erlaubt interessierten Bürger:innen den direkten, datengestützten Vergleich des regionalen Klimas anhand offizieller 30-Jahres-Normwerte (1991–2020).

**Detailprognose für eine lokale Veranstaltung**
«Zeig mir eine 10-Tage-Prognose für die Sportanlage Heerenschürli mit Stundenwerten.»
→ `meteo_forecast(location="Sportanlage Heerenschürli Zürich", days=10, hourly=True)`
Warum nützlich: Hilft bei der Planung von Sport- und Freizeitaktivitäten auf Quartierebene mit präzisen, stündlich aufgelösten Vorhersagen.

### 🤖 KI-Interessierte & Entwickler:innen
MCP-Enthusiast:innen, Forscher:innen, Prompt Engineers, öffentliche Verwaltung

**Kombination von Wetter- und Luftqualitätsdaten**
«Wie war Luftqualität und Wetter beim Schulhaus Leutschenbach gestern?»
→ `meteo_current(station="REH")`
→ `env_nabel_current(station="ZUE")`
Warum nützlich: Demonstriert eindrücklich die Stärke von MCP-Kombinationen, indem meteorologische Echtzeitdaten mit aktuellen Schadstoffwerten aus dem [swiss-environment-mcp](https://github.com/malkreide/swiss-environment-mcp) zu einem holistischen Umweltbild verknüpft werden.

**Automatisierte Schulstandort-Prognosen**
«Welche Schulen in Zürich haben am Mittwoch gutes Sporttag-Wetter?»
→ `zh_school_locations(city="Zürich")`
→ `meteo_school_check(location="Schulstandort X", activity="Sporttag")`
Warum nützlich: Zeigt, wie Geodaten aus anderen Servern (wie [zurich-opendata-mcp](https://github.com/malkreide/zurich-opendata-mcp)) als dynamische Parameter für hochaufgelöste Wettermodelle genutzt werden können, um skalierbare Planungs-Tools zu bauen.

### 🔧 Technische Referenz: Tool-Auswahl nach Anwendungsfall

| Ich möchte… | Tool(s) | Auth nötig? |
|-------------|---------|-------------|
| **eine Ampel-Empfehlung für Aussenaktivitäten abrufen** | `meteo_school_check` | Nein |
| **das Wetter für einen bestimmten Ort vorhersagen** | `meteo_forecast` | Nein |
| **aktuelle Messwerte einer Station in Echtzeit sehen** | `meteo_current` | Nein |
| **langjährige Klimanormwerte vergleichen** | `meteo_climate_normals` | Nein |
| **wissen, ob es aktuelle amtliche Warnungen gibt** | `meteo_warnings` | Nein |
| **herausfinden, welche Messstationen verfügbar sind** | `meteo_stations` | Nein |
