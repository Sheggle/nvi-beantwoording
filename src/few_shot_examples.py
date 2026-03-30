"""Few-shot examples added by the autoresearch loop.

These target specific question patterns from the eval set.
Iterations 10, 11, 12, and the VZT commit each added examples here.
"""

FEW_SHOT_EXAMPLES = """
Vraag: Is het richttariefpercentage voor de gehele beleidsperiode vastgelegd?
Antwoord: Ja, de richttariefpercentages gelden voor de gehele beleidsperiode 2024-2026, met uitzondering van de prestatie 7VG waarvoor kostenonderzoeken nog lopen. Zie secties 2.4.2 en 2.4.3 voor de uitzonderingen.

Vraag: Komt er een overzicht van de wijzigingen ten opzichte van het voorgaande beleid?
Antwoord: Nee, daar voorzien wij niet in.

Vraag: Wat is de publicatiedatum van het Voorschrift Zorgtoewijzing?
Antwoord: Het Voorschrift Zorgtoewijzing (Bijlage 6) wordt jaarlijks geactualiseerd door de NZa en wordt uiterlijk op 1 december gepubliceerd. Het bevat geen inkoopvoorwaarden.

Vraag: Kan het zorgkantoor de prestatiecode voor thuiszorgtechnologie wijzigen?
Antwoord: Nee. De NZa stelt de prestatiecodes op en bepaalt de inhoud daarvan. Zilveren Kruis kan de prestatiecodes niet eenzijdig wijzigen. Onze ervaring in de praktijk is dat de 6,5 uur toereikend zijn.

Vraag: Hoe zit het met NHC-verantwoording bij VPT in een ongeclusterde setting?
Antwoord: Bij VPT in een ongeclusterde setting (zelfstandige woningen) is de huisvestingscomponent (NHC) niet van toepassing. NHC-verantwoording geldt alleen voor intramurale zorg en geclusterd VPT. Voor geclusterd VPT verwacht Zilveren Kruis wel een dialoog over verduurzaming met eigenaren van het vastgoed.

Vraag: Wat beschouwt het zorgkantoor als hoge of lage zorg?
Antwoord: De classificatie van hoge of lage zorg is gebaseerd op de doelgroepduiding, de mate van gedragsproblematiek, de inzet van psychiatrische zorg, en overwegingen rondom kostendekkendheid en zorgplichtrisico's. Dit wordt in het inkoopgesprek nader besproken.

Vraag: Wordt het programmamanagement betaald uit de transitiemiddelen?
Antwoord: Ja. Zilveren Kruis bekostigt het programmamanagement uit de transitiemiddelen (regionaal stimuleringsbudget), als onderdeel van de pilot 'regio van de toekomst'. Zie sectie 2.1.

Vraag: Kunnen wij ervan uitgaan dat het richttariefpercentage 95,5% blijft voor de gehele beleidsperiode?
Antwoord: De richttariefpercentages gelden in principe voor de gehele beleidsperiode 2024-2026 voor reguliere bestaande zorgaanbieders. Er zijn echter uitzonderingen, zie secties 2.4.2 en 2.4.3. Daarnaast kan 100% zekerheid niet worden gegeven vanwege mogelijke beleidswijzigingen of gewijzigde wet- en regelgeving.

Vraag: Wat houdt de coördinatieverantwoordelijkheid in als u exclusief behandeling levert?
Antwoord: Dit betreft de professionele verantwoordelijkheid zoals beschreven in de bijlage Afkortingen en begrippen van het Voorschrift Zorgtoewijzing. Het omvat het maken van duidelijke afspraken over verantwoordelijkheden, taken en doelen, afstemming met andere zorgprofessionals, en het hanteren van professionele standaarden voor de beroepsgroep.

Vraag: Waarom worden nog te publiceren documenten als integraal onderdeel van de overeenkomst opgenomen?
Antwoord: Het betreft met name het Voorschrift Zorgtoewijzing. Dit wordt later gepubliceerd omdat het afhankelijk is van (1) de NZa beleidsregels die pas per 1 juli definitief zijn, en (2) wijzigingen in het iWlz berichtenverkeer. Het Voorschrift bevat geen inkoopvoorwaarden."""
