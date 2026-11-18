# LAN Messenger

Windows 10/11 va Python 3.11+ uchun lokal tarmoqda ishlaydigan, asyncio asosidagi TCP chat. Xabarlar UTF-8 JSON ko‘rinishida, 4 baytli uzunlik prefiksi bilan uzatiladi. Dastur uchun uchinchi tomon Python paketi talab qilinmaydi.

## Ishga tushirish

1. Server kompyuterida `LAN_Messenger` katalogini oching va terminalda:

   ```powershell
   py -3.11 server.py
   ```

   Server odatiy holatda `0.0.0.0:5000` manzilida tinglaydi. Boshqa port yoki bog‘lanish manzili kerak bo‘lsa:

   ```powershell
   py -3.11 server.py --host 0.0.0.0 --port 5000
   ```

   SQLite bazasi `messenger.db` nomi bilan server katalogida yaratiladi. Boshqa yo‘lni `--db C:\yo‘l\messenger.db` orqali berish mumkin. Serverni `Ctrl+C` bilan to‘xtating.

2. Server kompyuterining lokal IPv4 manzilini `ipconfig` buyrug‘i orqali aniqlang.

3. Har bir mijoz kompyuterida:

   ```powershell
   py -3.11 client.py
   ```

   Oyna ichida server IPv4 manzili, `5000` porti va takrorlanmagan foydalanuvchi nomini kiriting. Yoki manzilni oldindan berish mumkin:

   ```powershell
   py -3.11 client.py --host 192.168.1.100 --port 5000
   ```

   Umumiy xabar uchun “Hamma” tanlangan bo‘lsin. Shaxsiy xabar yuborish uchun ro‘yxatdan onlayn foydalanuvchini tanlang. Enter xabarni yuboradi. Ulanish uzilgach, o‘sha oynadagi “Ulanish” tugmasi orqali qayta ulanish mumkin.

## Windows Firewall

Server kompyuterida PowerShell'ni administrator sifatida ochib, TCP `5000` porti uchun Private tarmoqda kiruvchi qoidani qo‘shing:

```powershell
New-NetFirewallRule -DisplayName "LAN Messenger TCP 5000" -Direction Inbound -Protocol TCP -LocalPort 5000 -Action Allow -Profile Private
```

Mijozlar server bilan bir LAN/Wi-Fi ichida bo‘lishi kerak. Windows tarmoq profilini **Private** qilib belgilang. Bu qoidani faqat ishonchli LAN uchun ishlating.

## Testlar

Loyiha katalogida:

```powershell
py -3.11 -m unittest discover -s tests -v
```

Testlar protokol framing/UTF-8, parallel mijozlar, broadcast, shaxsiy xabar maxfiyligi, dublikat ism, kutilmagan uzilish va SQLite saqlanishini tekshiradi.

## Xavfsizlik chegaralari

Foydalanuvchi nomi bilan kirish haqiqiy autentifikatsiya emas: parol, shifrlash yoki identifikatsiya tekshiruvi yo‘q. Server va mijoz orasidagi trafik tarmoqda shifrlanmaydi. Shuning uchun dasturni faqat ishonchli, izolyatsiya qilingan LAN ichida ishlating; internetga ochmang va maxfiy ma’lumot yubormang. Server xabar yuboruvchini ulangan socket bilan bog‘laydi, xabar hajmini cheklaydi va foydalanuvchi nomining onlayn takrorlanishiga yo‘l qo‘ymaydi.
