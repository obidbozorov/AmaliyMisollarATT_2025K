# LAN Messenger

Windows 10/11 va Python 3.11+ uchun lokal tarmoqda ishlaydigan, asyncio asosidagi TCP chat. Xabarlar UTF-8 JSON ko‘rinishida, 4 baytli uzunlik prefiksi bilan uzatiladi. Dastur uchun uchinchi tomon Python paketi talab qilinmaydi.

## Ishga tushirish

1. Server kompyuterida `LAN_Messenger` katalogini oching va terminalda GUI boshqaruv oynasini ishga tushiring:

   ```powershell
   py -3.11 server.py
   ```

   Oynada bind IP (`0.0.0.0` barcha tarmoq adapterlari uchun), port va SQLite baza fayli yo‘lini sozlab, **Serverni ishga tushirish** tugmasini bosing. Onlayn foydalanuvchilar va loglar oynada ko‘rinadi; **To‘xtatish** serverni xavfsiz yopadi. Server odatiy holatda `0.0.0.0:5000` manzilida tinglaydi.

   Terminal rejimini ishlatish uchun:

   ```powershell
   py -3.11 server.py --console --host 0.0.0.0 --port 5000
   ```

   SQLite bazasi odatiy holatda `messenger.db` nomi bilan server katalogida yaratiladi. GUI’da yo‘lni kiritish yoki terminal rejimida `--db C:\yo‘l\messenger.db` orqali berish mumkin. Terminal serverini `Ctrl+C` bilan to‘xtating.

2. Server kompyuterining lokal IPv4 manzilini `ipconfig` buyrug‘i orqali aniqlang.

3. Har bir mijoz kompyuterida:

   ```powershell
   py -3.11 client.py
   ```

   Oyna ichida server IPv4 manzili, `5000` porti va takrorlanmagan foydalanuvchi nomini kiriting. Yoki manzilni oldindan berish mumkin:

   ```powershell
   py -3.11 client.py --host 192.168.1.100 --port 5000
   ```

   Umumiy xabarlar asosiy chat oynasida yuboriladi. Shaxsiy suhbat uchun onlayn foydalanuvchini ikki marta bosing yoki uni tanlab **Shaxsiy chatni ochish** tugmasini bosing. Har bir foydalanuvchi bilan yozishma alohida oynada ko‘rinadi; yangi shaxsiy xabar kelsa, tegishli oyna avtomatik ochiladi. Yopilgan oynani suhbatdoshni qayta tanlab ochish mumkin, tarix saqlanadi. Ulanish uzilgach, asosiy oynadagi **Ulanish** tugmasi orqali qayta ulanish mumkin.

## Windows Firewall

Server kompyuterida PowerShell'ni administrator sifatida ochib, TCP `5000` porti uchun Private tarmoqda kiruvchi qoidani qo‘shing:

```powershell
New-NetFirewallRule -DisplayName "LAN Messenger TCP 5000" -Direction Inbound -Protocol TCP -LocalPort 5000 -Action Allow -Profile Private
```

Mijozlar server bilan bir LAN/Wi-Fi ichida bo‘lishi kerak. Windows tarmoq profilini **Private** qilib belgilang. Bu qoidani faqat ishonchli LAN uchun ishlating.

## Ulanish muammolari

`WinError 1225` yoki “server ulanishni rad etdi” xabari odatda ko‘rsatilgan IP/portda server tinglamayotganini yoki ulanishni firewall rad etayotganini bildiradi:

1. Server kompyuterida server GUI oynasi ochiq va holati `Ishlayapti` ekanini, to‘g‘ri bind IP/port tanlanganini tekshiring.
2. Klientda `127.0.0.1` emas, server kompyuterining `ipconfig` orqali olingan IPv4 manzilini kiriting (agar klient va server bitta kompyuterda bo‘lmasa).
3. Klient kompyuteridan PowerShell’da `Test-NetConnection <server-ip> -Port 5000` buyrug‘ini bajaring. `TcpTestSucceeded: True` bo‘lishi kerak.
4. Server Windows Firewall qoidasining **Private** profil uchun yoqilganini va ikkala qurilma bir LAN/Wi-Fi’da ekanini tekshiring.

## Testlar

Loyiha katalogida:

```powershell
py -3.11 -m unittest discover -s tests -v
```

Testlar protokol framing/UTF-8, parallel mijozlar, broadcast, shaxsiy xabar maxfiyligi, dublikat ism, kutilmagan uzilish va SQLite saqlanishini tekshiradi.

## Xavfsizlik chegaralari

Foydalanuvchi nomi bilan kirish haqiqiy autentifikatsiya emas: parol, shifrlash yoki identifikatsiya tekshiruvi yo‘q. Server va mijoz orasidagi trafik tarmoqda shifrlanmaydi. Shuning uchun dasturni faqat ishonchli, izolyatsiya qilingan LAN ichida ishlating; internetga ochmang va maxfiy ma’lumot yubormang. Server xabar yuboruvchini ulangan socket bilan bog‘laydi, xabar hajmini cheklaydi va foydalanuvchi nomining onlayn takrorlanishiga yo‘l qo‘ymaydi.
