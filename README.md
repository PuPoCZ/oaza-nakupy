# Nákupy – Oáza klidu

Přehled nákupů vybavení a útraty k cíli do konce roku. Každý nákup má položky s kategorií, doklady a tři stavy: objednáno, zaplaceno, vyfakturováno.

- Stránka: https://pupocz.github.io/oaza-nakupy/ (přístup jen přes odkaz s klíčem `#k=…`)
- Data: Firebase Firestore, stejný projekt jako plánovač lůžek (`oaza-luzka`), kolekce `oaza_nakupy/{klíč}/nakupy`.
- Pravidla jsou v `firestore.rules` (obsahují i pravidla plánovače lůžek). Místo `KLIC` se v konzoli Firebase doplní skutečný klíč, do repozitáře se nepíše.
- Zkušební režim bez databáze: `?demo` (data jen v prohlížeči).
- Záloha a obnova: Nastavení → Stáhnout zálohu / Nahrát ze zálohy.
