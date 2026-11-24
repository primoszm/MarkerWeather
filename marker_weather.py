import sys, subprocess
import json, math, os, threading, urllib.parse, urllib.request, tkinter as tk, time, io, re, unicodedata, random
from datetime import datetime
from PIL import Image, ImageDraw, ImageFont, ImageTk, ImageFilter, ImageOps, ImageChops

W,H=400,700
WHITE='#f7f7f7'; YELLOW='#ffc928'
BASE=os.path.dirname(os.path.abspath(__file__))
CONFIG=os.path.join(os.path.expanduser('~'),'.marker_weather.json')
PHOTO_CACHE=os.path.join(os.path.expanduser('~'),'.marker_weather_photos')
PHOTO_TTL=7*24*3600
COMMONS_API='https://commons.wikimedia.org/w/api.php'

def city_key(city):
    normalized=unicodedata.normalize('NFKD',city).encode('ascii','ignore').decode().lower()
    return re.sub(r'[^a-z0-9_-]+','_',normalized).strip('_')[:65] or 'city'

def commons_photos(city):
    """Zwraca kandydatów ze zdjęciami z Wikimedia Commons."""
    params={'action':'query','generator':'search',
            'gsrsearch':'filetype:bitmap '+city+' skyline panorama cityscape',
            'gsrnamespace':6,'gsrlimit':50,'prop':'imageinfo',
            'iiprop':'url|extmetadata|size','iiurlwidth':1000,
            'format':'json','formatversion':2}
    data=fetch(COMMONS_API+'?'+urllib.parse.urlencode(params))
    pages=data.get('query',{}).get('pages',[])
    words=[city_key(w) for w in city.split() if len(w)>2]
    candidates=[]
    for page in pages:
        title=page.get('title','')
        if not any(word in city_key(title) for word in words):continue
        info=(page.get('imageinfo') or [{}])[0]
        meta=info.get('extmetadata') or {}
        license_name=(meta.get('LicenseShortName') or {}).get('value','').strip()
        if not license_name.upper().startswith(('CC BY','CC0','PUBLIC DOMAIN','PD-')):continue
        url=info.get('thumburl') or info.get('url','')
        if not url.startswith('https://'):continue
        if not url.lower().split('?')[0].endswith(('.jpg','.jpeg','.png','.webp')):continue
        candidates.append({'url':url,'title':title,'license':license_name,
            'author':re.sub('<[^>]+>','',(meta.get('Artist') or {}).get('value',''))[:300],
            'source':info.get('descriptionurl','')})
    return candidates


def download_commons_photo(candidate):
    req=urllib.request.Request(candidate['url'],headers={
        'User-Agent':'MarkerWeather/2.4 (desktop weather widget; Wikimedia Commons attribution)'})
    with urllib.request.urlopen(req,timeout=15) as response:
        raw=response.read(8_000_001)
    if len(raw)>8_000_000:raise ValueError('Zdjęcie jest za duże')
    with Image.open(io.BytesIO(raw)) as photo:
        if photo.width<400 or photo.height<300:raise ValueError('Za mała rozdzielczość')
        fitted=ImageOps.fit(photo.convert('RGB'),(W,H),
                            method=Image.Resampling.LANCZOS,centering=(0.5,0.5))
    return fitted, {k:v for k,v in candidate.items() if k!='url'}


def font(size, bold=False):
    candidates=[r'C:\Windows\Fonts\segoeprb.ttf' if bold else r'C:\Windows\Fonts\segoepr.ttf',r'C:\Windows\Fonts\comicbd.ttf' if bold else r'C:\Windows\Fonts\comic.ttf',r'C:\Windows\Fonts\seguisb.ttf',r'C:\Windows\Fonts\arial.ttf']
    for p in candidates:
        if os.path.isfile(p): return ImageFont.truetype(p,size)
    return ImageFont.load_default()

def fetch(url):
    req=urllib.request.Request(url,headers={'User-Agent':'MarkerWeather/1.0'})
    with urllib.request.urlopen(req,timeout=12) as r:return json.load(r)

def weather_type(code,is_day):
    if code in (0,1):return 'sun' if is_day else 'moon','Bezchmurnie' if code==0 else 'Przeważnie pogodnie'
    if code in (2,3):return 'cloud','Częściowe zachmurzenie' if code==2 else 'Pochmurno'
    if code in (45,48):return 'fog','Mgła'
    if code in (51,53,55,56,57,61,63,65,66,67,80,81,82):return 'rain','Deszcz / mżawka'
    if code in (71,73,75,77,85,86):return 'snow','Opady śniegu'
    if code in (95,96,99):return 'storm','Burza'
    return 'cloud','Zmienna pogoda'

class Widget:
    def __init__(self):
        self.root=tk.Tk();self.root.title('Marker Weather');self.root.geometry('400x700+100+100');self.root.overrideredirect(True);self.root.attributes('-topmost',False)
        self.canvas=tk.Canvas(self.root,width=W,height=H,highlightthickness=0,bg='#111111');self.canvas.pack()
        self.city='Gdańsk';self.lat=54.352;self.lon=18.6466;self.data=None;self.error='';self.busy=False;self.top=False;self.opacity=100;self.theme='standard';self.background_cache={};self.theme_fade_from=None;self.theme_fade_start=0;self.old_kind=None;self.transition_start=0;self.transition_from=None;self.transition_to=None;self.last_kind=None;self.photo=None;self.photo_meta=None;self.photo_city=None;self.photo_busy=False;self.photo_request=0;self.menu_panel=None;self.appearance_open=True;self.city_open=False;self.opacity_open=False
        self.startup_initialized=False
        try:
            with open(CONFIG,encoding='utf8') as f:
                c=json.load(f);self.startup_initialized=bool(c.get('startup_initialized',False));self.city=c.get('city',self.city);self.lat=c.get('lat',self.lat);self.lon=c.get('lon',self.lon);self.opacity=max(30,min(100,int(c.get('opacity',100))));self.theme=c.get('theme','standard') if c.get('theme','standard') in ('standard','landscape','city') else 'standard'
        except (OSError,ValueError,TypeError):pass
        self.initialize_startup()
        self.root.attributes('-alpha',self.opacity/100)
        self.root.bind('<ButtonPress-1>',self.drag_start);self.root.bind('<B1-Motion>',self.drag_move)
        self.canvas.bind('<Button-1>',self.dismiss_menu)
        self.root.bind('<Button-3>',self.menu);self.root.bind('<Escape>',self.escape_menu)
        self.root.bind('<Double-Button-1>',lambda e:self.change_city())
        self.tkimg=None;self.tick();self.refresh();self.ensure_city_photo();self.root.mainloop()
    def drag_start(self,e):self.dx=e.x_root-self.root.winfo_x();self.dy=e.y_root-self.root.winfo_y()
    def drag_move(self,e):self.root.geometry(f'+{e.x_root-self.dx}+{e.y_root-self.dy}')
    def escape_menu(self,e=None):
        if self.menu_panel is not None:self.dismiss_menu()
        else:self.root.destroy()

    def dismiss_menu(self,e=None):
        panel=self.menu_panel
        self.menu_panel=None
        if panel is not None:
            try:
                if panel.winfo_exists():panel.destroy()
            except tk.TclError:pass

    def menu(self,e=None):
        """Nieprzezroczyste, niezależne menu z rozwijanymi sekcjami."""
        if e is not None:
            self.menu_xy=(e.x_root,e.y_root)
        self.dismiss_menu()
        bg='#191c22';hover='#303640';fg='#f4f5f7';muted='#afb6c3';blue='#36aaff'
        panel=tk.Toplevel(self.root)
        self.menu_panel=panel
        panel.withdraw()
        panel.overrideredirect(True)
        panel.configure(bg='#858b94')
        panel.attributes('-alpha',1.0)
        panel.attributes('-topmost',True)
        panel.resizable(False,False)
        panel.bind('<Escape>',self.dismiss_menu)
        panel.bind('<FocusOut>',lambda ev:self.root.after(160,self.dismiss_if_unfocused))
        inside=tk.Frame(panel,bg=bg,width=318)
        inside.pack(fill='both',expand=True,padx=1,pady=1)
        inside.pack_propagate(True)

        def row(text,icon,command,active=False,indent=0):
            color=hover if active else bg
            f=tk.Frame(inside,bg=color,height=35)
            f.pack(fill='x',padx=10,pady=1)
            f.pack_propagate(False)
            symbol=tk.Label(f,text=icon,font=('Segoe UI Symbol',15),fg=blue if active else fg,
                            bg=color,anchor='center',bd=0,padx=0,pady=0)
            symbol.place(x=0,y=0,width=38,height=35)
            label=tk.Label(f,text=text,font=('Segoe UI',11),fg=fg,bg=color,anchor='w',bd=0,padx=0,pady=0)
            label.place(x=44+indent,y=0,relwidth=1,width=-44-indent,height=35)
            for w in (f,symbol,label):
                w.bind('<Button-1>',lambda event,fn=command:fn())
            return f

        def toggle(section):
            setattr(self,section,not getattr(self,section))
            self.menu()

        row('Ustawienia','⚙',lambda:None)
        row('Wygląd aplikacji  '+('⌄' if self.appearance_open else '›'),
            '▣',lambda:toggle('appearance_open'),True)
        if self.appearance_open:
            for key,name,subtitle in [
                ('standard','Standardowy',''),
                ('landscape','Graficzny',''),
                ('city','Miasto','')]:
                chosen=self.theme==key
                row(name,'◉' if chosen else '◯',lambda k=key:self.choose_menu_theme(k))

        tk.Frame(inside,bg='#50545a',height=1).pack(fill='x',padx=12,pady=5)
        row('Zawsze na wierzchu  '+('✓' if self.top else '○'),'⌁',self.menu_toggle_top)
        row('Autostart  '+('✓' if self.startup_enabled() else '○'),'⏻',self.menu_toggle_startup)

        row('Wybierz miasto  '+('⌄' if self.city_open else '›'),'⌖',
            lambda:toggle('city_open'),self.city_open)
        if self.city_open:
            city_box=tk.Frame(inside,bg=bg)
            city_box.pack(fill='x',padx=22,pady=(3,7))
            city_label=tk.Label(city_box,text='Wpisz nazwę miasta:',font=('Segoe UI',11),
                                fg=muted,bg=bg,anchor='w')
            city_label.pack(fill='x')
            city_entry=tk.Entry(city_box,font=('Segoe UI',11),bg='#343a43',fg=fg,
                                insertbackground=fg,relief='flat',bd=5)
            city_entry.insert(0,self.city)
            city_entry.pack(fill='x',pady=3)
            def submit_city(event=None):
                name=city_entry.get().strip()
                if name:
                    self.dismiss_menu()
                    self.lookup(name)
            city_entry.bind('<Return>',submit_city)
            apply_btn=tk.Button(city_box,text='Ustaw miasto',command=submit_city,
                                font=('Segoe UI',11),bg='#344e70',fg=fg,
                                activebackground='#3a689c',activeforeground=fg,
                                relief='flat',cursor='hand2')
            apply_btn.pack(anchor='e',pady=(1,0))

        row('Przezroczystość  '+str(self.opacity)+'%  '+
            ('⌄' if self.opacity_open else '›'),'◐',
            lambda:toggle('opacity_open'),self.opacity_open)
        if self.opacity_open:
            slider_line=tk.Frame(inside,bg=bg)
            slider_line.pack(fill='x',padx=18,pady=(0,7))
            value=tk.Label(slider_line,text=f'{self.opacity}%',font=('Segoe UI',11),
                           fg=muted,bg=bg,width=5)
            value.pack(side='right')
            def update_opacity(val):
                self.opacity=int(float(val))
                self.root.attributes('-alpha',self.opacity/100)
                value.configure(text=f'{self.opacity}%')
                self.save_config()
            slider=tk.Scale(slider_line,from_=30,to=100,orient='horizontal',
                            showvalue=False,command=update_opacity,
                            bg=bg,fg=fg,highlightthickness=0,
                            troughcolor='#414852',activebackground=blue,
                            length=230,sliderlength=16,bd=0)
            slider.set(self.opacity)
            slider.pack(side='left')

        tk.Frame(inside,bg='#50545a',height=1).pack(fill='x',padx=12,pady=5)
        row('O aplikacji','ⓘ',self.show_about)
        if self.theme=='city':
            row('Źródło zdjęcia','ⓘ',self.photo_credit)
        row('Zamknij','✕',self.root.destroy)

        panel.update_idletasks()
        w=320
        h=inside.winfo_reqheight()+2
        x,y=getattr(self,'menu_xy',(self.root.winfo_rootx()+70,self.root.winfo_rooty()+90))
        screen_w=panel.winfo_screenwidth();screen_h=panel.winfo_screenheight()
        x=max(0,min(x,screen_w-w));y=max(0,min(y,screen_h-h))
        panel.geometry(f'{w}x{h}+{x}+{y}')
        panel.deiconify()
        panel.lift()
        panel.focus_force()

    def dismiss_if_unfocused(self):
        panel=self.menu_panel
        if panel is None:return
        try:
            focused=panel.focus_get()
            # Nie zamykaj podczas przesuwania suwaka ani po kliknięciu w menu.
            if focused is None or (focused!=panel and not str(focused).startswith(str(panel))):
                self.dismiss_menu()
        except tk.TclError:pass


    def choose_menu_theme(self,theme):
        self.set_theme(theme)
        self.menu()

    def startup_command(self):
        args=[sys.executable] if getattr(sys,'frozen',False) else [sys.executable,os.path.abspath(__file__)]
        return subprocess.list2cmdline(args)

    def startup_enabled(self):
        if sys.platform!='win32':return False
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,r'Software\Microsoft\Windows\CurrentVersion\Run') as key:
                value,_=winreg.QueryValueEx(key,'MarkerWeather')
                return value==self.startup_command()
        except OSError:return False

    def initialize_startup(self):
        if sys.platform!='win32' or self.startup_initialized or not getattr(sys,'frozen',False):return
        import winreg
        try:
            with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER,r'Software\Microsoft\Windows\CurrentVersion\Run',0,winreg.KEY_SET_VALUE) as key:
                winreg.SetValueEx(key,'MarkerWeather',0,winreg.REG_SZ,self.startup_command())
            self.startup_initialized=True
            self.save_config()
        except OSError:pass

    def menu_toggle_startup(self):
        from tkinter import messagebox
        try:
            if sys.platform!='win32':raise OSError('Autostart jest dostępny tylko w Windows.')
            import winreg
            with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER,r'Software\Microsoft\Windows\CurrentVersion\Run',0,winreg.KEY_SET_VALUE) as key:
                if not self.startup_enabled():
                    winreg.SetValueEx(key,'MarkerWeather',0,winreg.REG_SZ,self.startup_command())
                else:
                    try:winreg.DeleteValue(key,'MarkerWeather')
                    except FileNotFoundError:pass
            self.startup_initialized=True
            self.save_config()
        except OSError as exc:
            messagebox.showerror('MarkerWeather',f'Nie udało się zmienić autostartu: {exc}',parent=self.root)
        if self.menu_panel is not None: self.menu()

    def menu_toggle_top(self):
        self.toggle_top()
        self.menu()

    def menu_change_city(self):
        self.dismiss_menu()
        self.change_city()

    def menu_refresh(self):
        self.dismiss_menu()
        self.refresh()

    def show_about(self):
        """Ciemny, nieprzezroczysty panel informacji zamiast systemowego messagebox."""
        self.dismiss_menu()
        bg='#191c22'
        fg='#f4f5f7'
        muted='#afb6c3'
        border='#858b94'
        blue='#36aaff'

        about=tk.Toplevel(self.root)
        about.withdraw()
        about.overrideredirect(True)
        about.configure(bg=border)
        about.attributes('-alpha',1.0)
        about.attributes('-topmost',True)
        about.resizable(False,False)

        frame=tk.Frame(about,bg=bg)
        frame.pack(fill='both',expand=True,padx=1,pady=1)
        heading=tk.Frame(frame,bg=bg)
        heading.pack(fill='x',padx=18,pady=(15,5))
        tk.Label(heading,text='ⓘ',font=('Segoe UI Symbol',17),
                 fg=blue,bg=bg).pack(side='left')
        tk.Label(heading,text='O aplikacji',font=('Segoe UI',12,'bold'),
                 fg=fg,bg=bg).pack(side='left',padx=(10,0))
        tk.Button(heading,text='✕',font=('Segoe UI',12),fg=muted,bg=bg,
                  activeforeground=fg,activebackground='#303640',
                  bd=0,relief='flat',command=about.destroy,
                  cursor='hand2').pack(side='right')
        tk.Frame(frame,bg='#50545a',height=1).pack(fill='x',padx=18,pady=(2,12))
        tk.Label(frame,text='MarkerWheater stworzył:',
                 font=('Segoe UI',11),fg=fg,bg=bg,anchor='w').pack(fill='x',padx=23)
        tk.Label(frame,text='Przemysław Michalski',
                 font=('Segoe UI',12,'bold'),fg=fg,bg=bg,anchor='w').pack(fill='x',padx=23,pady=(7,0))
        tk.Label(frame,text='primoszm@gmail.com',
                 font=('Segoe UI',11),fg=blue,bg=bg,anchor='w').pack(fill='x',padx=23,pady=(5,16))
        tk.Button(frame,text='Zamknij',font=('Segoe UI',10),
                  fg=fg,bg='#303640',activeforeground=fg,
                  activebackground='#414b59',relief='flat',bd=0,
                  padx=16,pady=6,command=about.destroy,
                  cursor='hand2').pack(anchor='e',padx=18,pady=(0,15))
        about.bind('<Escape>',lambda e:about.destroy())
        about.update_idletasks()
        w,h=335,about.winfo_reqheight()
        x=self.root.winfo_rootx()+(self.root.winfo_width()-w)//2
        y=self.root.winfo_rooty()+max(15,(self.root.winfo_height()-h)//2)
        x=max(0,min(x,about.winfo_screenwidth()-w))
        y=max(0,min(y,about.winfo_screenheight()-h))
        about.geometry(f'{w}x{h}+{x}+{y}')
        about.deiconify()
        about.lift()
        about.focus_force()

    def set_theme(self,theme):
        if theme not in ('standard','landscape','city'):return
        if theme==self.theme and theme=='city':
            self.ensure_city_photo(force_new=True)
            return
        if theme!=self.theme:
            self.theme_fade_from=self.theme;self.theme_fade_start=time.monotonic()
            self.theme=theme;self.save_config();self.ensure_city_photo();self.render()
    def photo_credit(self):
        from tkinter import messagebox
        if not self.photo_meta:
            messagebox.showinfo('Zdjęcie miasta','Brak fotografii. Wyświetlana jest lokalna ilustracja miasta.',parent=self.root)
            return
        m=self.photo_meta
        messagebox.showinfo('Wikimedia Commons',
            'Fotografia: '+m.get('title','')+'\\nAutor: '+m.get('author','')+
            '\\nLicencja: '+m.get('license','')+'\\nŹródło: '+m.get('source',''),parent=self.root)

    def ensure_city_photo(self,force_new=False):
        if self.theme!='city':return
        city=self.city
        if self.photo_city==city and self.photo is not None and not force_new:return
        self.photo_request+=1
        request_id=self.photo_request
        self.photo_busy=True
        def work():
            photo=None;meta=None
            try:
                os.makedirs(PHOTO_CACHE,exist_ok=True)
                base=os.path.join(PHOTO_CACHE,city_key(city))
                catalog_path=base+'_catalog.json'
                # Zapamiętujemy listę zdjęć, a nie tylko jedno zdjęcie.
                catalog=[]
                if os.path.isfile(catalog_path):
                    with open(catalog_path,encoding='utf-8') as f:catalog=json.load(f)
                if not catalog or time.time()-os.path.getmtime(catalog_path)>PHOTO_TTL:
                    try:
                        fresh=commons_photos(city)
                        if fresh:
                            catalog=fresh
                            with open(catalog_path,'w',encoding='utf-8') as f:
                                json.dump(catalog,f,ensure_ascii=False)
                    except Exception:pass
                last_source=(self.photo_meta or {}).get('source','')
                candidates=list(catalog)
                random.shuffle(candidates)
                if len(candidates)>1:
                    candidates.sort(key=lambda item:item.get('source','')==last_source)
                for candidate in candidates:
                    try:
                        photo,meta=download_commons_photo(candidate)
                        break
                    except Exception:continue
                # Awaryjnie: poprzednia fotografia, jeśli brak sieci.
                if photo is None and not force_new:
                    path=base+'.jpg';info_path=base+'.json'
                    if os.path.isfile(path) and os.path.isfile(info_path):
                        with open(info_path,encoding='utf-8') as f:meta=json.load(f)
                        with Image.open(path) as img:photo=img.convert('RGB').copy()
                if photo is not None and meta is not None:
                    photo.save(base+'.jpg',quality=88)
                    with open(base+'.json','w',encoding='utf-8') as f:
                        json.dump(meta,f,ensure_ascii=False)
            except Exception:pass
            def apply_photo():
                if request_id!=self.photo_request or self.city!=city:return
                self.photo_busy=False
                if photo is not None:
                    self.photo=photo;self.photo_meta=meta;self.photo_city=city
                    self.background_cache={k:v for k,v in self.background_cache.items() if k[0]!='city'}
                    self.render()
            try:self.root.after(0,apply_photo)
            except RuntimeError:pass
        threading.Thread(target=work,daemon=True).start()

    def toggle_top(self):self.top=not self.top;self.root.attributes('-topmost',self.top)
    def save_config(self):
        try:
            with open(CONFIG,'w',encoding='utf8') as f:
                json.dump({'city':self.city,'lat':self.lat,'lon':self.lon,'opacity':self.opacity,'theme':self.theme,'startup_initialized':self.startup_initialized},f,ensure_ascii=False)
        except OSError:pass
    def opacity_dialog(self):
        self.menu()

    def change_city(self):
        dlg=tk.Toplevel(self.root);dlg.title('Wybierz miasto');dlg.geometry('310x115');dlg.resizable(False,False);dlg.attributes('-topmost',True)
        tk.Label(dlg,text='Wpisz nazwę miasta:').pack(pady=(10,3));v=tk.StringVar(value=self.city);entry=tk.Entry(dlg,textvariable=v,width=34);entry.pack();entry.focus_set()
        def go():
            name=v.get().strip()
            if name:dlg.destroy();self.lookup(name)
        tk.Button(dlg,text='Ustaw miasto',command=go).pack(pady=7);entry.bind('<Return>',lambda e:go())
    def lookup(self,name):
        self.error='Szukam miasta…';self.render()
        def work():
            try:
                q=urllib.parse.urlencode({'name':name,'count':1,'language':'pl','format':'json'})
                obj=fetch('https://geocoding-api.open-meteo.com/v1/search?'+q)
                if not obj.get('results'):raise ValueError('Nie znaleziono miasta')
                p=obj['results'][0]
                self.root.after(0,lambda:self.set_city(p['name'],p['latitude'],p['longitude']))
            except Exception as ex:self.root.after(0,lambda msg=str(ex):self.set_error(msg))
        threading.Thread(target=work,daemon=True).start()
    def set_city(self,name,lat,lon):
        self.city=name;self.lat=lat;self.lon=lon
        self.photo=None;self.photo_meta=None;self.photo_city=None;self.background_cache.clear()
        self.save_config();self.ensure_city_photo(force_new=True)
        self.refresh()
    def set_error(self,msg):self.error=msg;self.busy=False;self.render()
    def refresh(self):
        self.root.after(15*60*1000,self.refresh)
        if self.busy:return
        self.busy=True;self.error='';self.render()
        def work():
            try:
                q=urllib.parse.urlencode({'latitude':self.lat,'longitude':self.lon,'current':'temperature_2m,relative_humidity_2m,precipitation,weather_code,is_day,wind_speed_10m','daily':'sunrise,sunset,precipitation_probability_max,weather_code,temperature_2m_max,temperature_2m_min','timezone':'auto','forecast_days':5})
                data=fetch('https://api.open-meteo.com/v1/forecast?'+q)
                self.root.after(0,lambda:self.apply(data))
            except Exception:self.root.after(0,lambda:self.set_error('Brak połączenia z pogodą'))
        threading.Thread(target=work,daemon=True).start()
    def apply(self,data):
        previous=self.last_kind
        current=data.get('current',{})
        new_kind=weather_type(current.get('weather_code',2),current.get('is_day',1))[0]
        self.data=data;self.busy=False;self.error=''
        if previous is not None and previous!=new_kind:
            self.transition_from=previous;self.transition_to=new_kind;self.transition_start=time.monotonic()
        self.last_kind=new_kind
        self.ensure_city_photo();self.render()
    def tick(self):
        self.render()
        active=(self.transition_from is not None and time.monotonic()-self.transition_start<1.5) or (self.theme_fade_from is not None and time.monotonic()-self.theme_fade_start<0.9)
        self.root.after(70 if active else 1000,self.tick)
    def make_standard_background(self):
        im=Image.new('RGB',(W,H));px=im.load()
        for y in range(H):
            for x in range(W):
                glow=max(0,1-math.hypot(x-350,(y-180)*0.85)/470)
                n=int(13+21*(y/H)+21*glow)
                px[x,y]=(n,n,n+1)
        return im

    def make_background(self,kind,is_day):
        # Tło rysowane lokalnie: nie wymaga obrazów ani kluczy API.
        # Zależne od kodu pogody i dnia/nocy.
        daylight=bool(is_day)
        if kind in ('rain','storm','snow','fog'):
            top=(12,22,42) if daylight else (8,12,27)
            bottom=(61,75,89) if daylight else (32,38,55)
        elif kind in ('sun','moon'):
            top=(24,56,94) if daylight else (9,15,39)
            bottom=(139,112,89) if daylight else (39,43,73)
        else:
            top=(23,44,73) if daylight else (13,20,42)
            bottom=(95,97,103) if daylight else (43,48,65)
        im=Image.new('RGB',(W,H));px=im.load()
        for y in range(H):
            t=y/(H-1)
            for x in range(W):
                glow=max(0,1-math.hypot(x-315,y-245)/490)*0.16
                px[x,y]=tuple(min(255,int(a*(1-t)+b*t+glow*35)) for a,b in zip(top,bottom))
        layer=Image.new('RGBA',(W,H));d=ImageDraw.Draw(layer,'RGBA')
        if kind in ('sun','cloud','moon'):
            if daylight:
                d.ellipse((245,155,355,265),fill=(255,196,83,120))
            else:
                d.ellipse((250,160,325,235),fill=(224,231,244,115))
        # Rozmyte warstwy chmur w górnej połowie.
        for i in range(8):
            x=((i*117+19)%520)-80;y=150+(i*43)%220
            shade=175 if daylight else 112
            d.ellipse((x-105,y-34,x+115,y+33),fill=(shade,shade+5,min(255,shade+15),26 if kind=='sun' else 52))
        layer=layer.filter(ImageFilter.GaussianBlur(25))
        im=Image.alpha_composite(im.convert('RGBA'),layer)
        if kind in ('rain','storm','snow'):
            precip=Image.new('RGBA',(W,H));p=ImageDraw.Draw(precip,'RGBA')
            for i in range(48):
                x=(i*79+37)%W;y=(i*137+43)%510+90
                if kind=='snow':p.ellipse((x,y,x+3,y+3),fill=(242,248,255,115))
                else:p.line((x,y,x-9,y+25),fill=(125,190,245,70),width=2)
            im=Image.alpha_composite(im,precip)
        # Ciemna nakładka utrzymuje czytelność białych napisów.
        overlay=Image.new('RGBA',(W,H),(0,0,0,92))
        return Image.alpha_composite(im,overlay).convert('RGB')

    def get_theme_background(self,theme,kind,is_day):
        if theme in ('graphic','sky'):theme='standard'  # migracja usuniętego motywu
        key=(theme,kind,bool(is_day),self.city if theme=='city' else '')
        if key not in self.background_cache:
            if len(self.background_cache)>32:self.background_cache.clear()
            self.background_cache[key]=self.build_theme_background(theme,kind,is_day)
        return self.background_cache[key].copy()

    def build_theme_background(self,theme,kind,is_day):
        if theme=='standard':return self.make_standard_background()
        if theme=='city' and self.photo is not None and self.photo_city==self.city:
            im=self.photo.copy().convert('RGBA')
            tint=Image.new('RGBA',(W,H),(12,20,34,45 if is_day else 130))
            im=Image.alpha_composite(im,tint)
            # Deszcz, śnieg, mgła i nocna tonacja nakładane na fotografię.
            effects=Image.new('RGBA',(W,H),(0,0,0,0))
            fx=ImageDraw.Draw(effects,'RGBA')
            if kind in ('rain','storm'):
                for i in range(72):
                    x=(i*73+29)%W;y=(i*131+47)%H
                    fx.line((x,y,x-8,y+24),fill=(140,195,255,115),width=2)
            elif kind=='snow':
                for i in range(95):
                    x=(i*97+19)%W;y=(i*137+51)%H
                    fx.ellipse((x,y,x+3,y+3),fill=(250,252,255,175))
            elif kind=='fog':
                fx.rectangle((0,0,W,H),fill=(215,225,232,85))
            elif kind in ('sun','moon') and is_day:
                fx.ellipse((270,65,355,150),fill=(255,204,108,65))
            im=Image.alpha_composite(im,effects)
            im=Image.alpha_composite(im,Image.new('RGBA',(W,H),(0,0,0,85)))
            return im.convert('RGB')
        im=self.make_background(kind,is_day).convert('RGBA')
        layer=Image.new('RGBA',(W,H),(0,0,0,0));d=ImageDraw.Draw(layer,'RGBA')
        day=bool(is_day)
        # Krajobraz jest ilustracją; Miasto ma awaryjną ilustrację.
        if theme=='landscape':
            # Warstwowy horyzont, pagórki, drzewa i ziemia / śnieg.
            d.polygon([(0,535),(70,475),(132,526),(218,449),(315,520),(400,473),(400,700),(0,700)],fill=(72,91,109,170) if day else (30,45,64,210))
            d.polygon([(0,588),(98,520),(172,578),(266,499),(400,562),(400,700),(0,700)],fill=(43,65,69,220) if day else (19,33,44,235))
            ground=(210,222,231,180) if kind=='snow' else ((34,65,47,210) if day else (14,31,34,235))
            d.polygon([(0,610),(85,582),(190,610),(290,569),(400,606),(400,700),(0,700)],fill=ground)
            for x in (24,65,340,375):
                y=570+(x*7)%35
                d.polygon([(x,y-55),(x-19,y-9),(x+19,y-9)],fill=(12,35,35,215))
                d.rectangle((x-3,y-10,x+3,y+13),fill=(24,28,32,230))
        elif theme=='city':
            # Stylizowana panorama miasta; dla Gdańska dodajemy charakterystyczny żuraw i wieże.
            skyline=(34,40,52,230) if day else (15,22,35,245)
            for i in range(14):
                x=i*34-8;h=40+(i*37)%75
                d.rectangle((x,620-h,x+29,700),fill=skyline)
                d.polygon([(x-3,620-h),(x+14,602-h),(x+32,620-h)],fill=skyline)
                for wx in (x+8,x+19):
                    for wy in range(630-h,676,21):
                        if (wx+wy)%3:d.rectangle((wx,wy,wx+3,wy+6),fill=(250,186,99,135))
            if 'gda' in self.city.lower():
                # Uproszczona sylwetka Żurawia nad Motławą.
                d.rectangle((178,490,214,660),fill=skyline)
                d.polygon([(168,490),(196,463),(224,490)],fill=skyline)
                d.line((210,492,245,510),fill=(28,33,44,255),width=9)
                d.line((242,510,242,563),fill=(28,33,44,255),width=4)
                d.rectangle((310,472,329,655),fill=skyline)
                d.polygon([(303,472),(320,428),(336,472)],fill=skyline)
            d.rectangle((0,660,400,700),fill=(17,31,46,185))
            for i in range(20):
                x=(i*53)%400
                d.line((x,674+(i*11)%24,x+18,674+(i*11)%24),fill=(243,178,91,65),width=2)
        im=Image.alpha_composite(im,layer)
        # Ciemna nakładka dla kontrastu tekstu i prognozy.
        shade=Image.new('RGBA',(W,H),(0,0,0,75))
        return Image.alpha_composite(im,shade).convert('RGB')

    def render(self):
        current=self.data.get('current',{}) if self.data else {}
        kind,_=weather_type(current.get('weather_code',2),current.get('is_day',1))
        day=current.get('is_day',1)
        im=self.get_theme_background(self.theme,kind,day)
        if self.theme_fade_from is not None:
            t=min(1.0,(time.monotonic()-self.theme_fade_start)/0.9)
            if t>=1.0:self.theme_fade_from=None
            else:im=Image.blend(self.get_theme_background(self.theme_fade_from,kind,day),im,t)
        d=ImageDraw.Draw(im)
        def centered(txt,y,size,color=WHITE,bold=False):
            f=font(size,bold);b=d.textbbox((0,0),txt,font=f);d.text(((W-(b[2]-b[0]))/2,y),txt,font=f,fill=color,stroke_width=0)
        now=datetime.now();centered(now.strftime('%H:%M'),24,82,WHITE,True)
        centered(self.city,138,27)
        current=self.data.get('current',{}) if self.data else {};daily=self.data.get('daily',{}) if self.data else {}
        kind,desc=weather_type(current.get('weather_code',2),current.get('is_day',1))
        if self.transition_from is not None:
            t=min(1.0,(time.monotonic()-self.transition_start)/1.5)
            if t>=1.0:
                self.transition_from=None
                self.draw_icon(d,kind)
            else:
                before=Image.new('RGBA',(W,H),(0,0,0,0))
                after=Image.new('RGBA',(W,H),(0,0,0,0))
                self.draw_icon(ImageDraw.Draw(before),self.transition_from)
                self.draw_icon(ImageDraw.Draw(after),self.transition_to)
                before.putalpha(before.getchannel('A').point(lambda v:int(v*(1-t))))
                after.putalpha(after.getchannel('A').point(lambda v:int(v*t)))
                im=Image.alpha_composite(im.convert('RGBA'),before)
                im=Image.alpha_composite(im,after).convert('RGB')
                d=ImageDraw.Draw(im)
        else:self.draw_icon(d,kind)
        if 'temperature_2m' in current:
            centered(f"{round(current['temperature_2m'])}°C",332,76,WHITE,True)
        else:centered('—°C',332,76,WHITE,True)
        centered(desc,430,21)
        d.line((18,482,382,482),fill='#777777',width=1)
        wind=round(current.get('wind_speed_10m',0));hum=round(current.get('relative_humidity_2m',0))
        chance=daily.get('precipitation_probability_max',[None])[0]
        sunrise=daily.get('sunrise',[''])[0][-5:];sunset=daily.get('sunset',[''])[0][-5:]
        vals=[('WIATR',f'{wind} km/h' if self.data else '—'),('OPADY',f'{chance}%' if chance is not None else '—'),('WILG.',f'{hum}%' if self.data else '—'),('SŁOŃCE',f'{sunrise}\n{sunset}' if sunrise else '—')]
        for i,(lab,val) in enumerate(vals):
            x=i*100+50
            if i:d.line((i*100,492,i*100,589),fill='#777777',width=1)
            self.draw_detail_icon(d,i,x,508)
            f=font(12,True);b=d.textbbox((0,0),lab,font=f);d.text((x-(b[2]-b[0])/2,531),lab,font=f,fill=YELLOW)
            for j,line in enumerate(val.split('\n')):
                f2=font(14,True);b2=d.textbbox((0,0),line,font=f2);d.text((x-(b2[2]-b2[0])/2,548+j*17),line,font=f2,fill=WHITE)
        # Prognoza na kolejne cztery dni (bez dnia dzisiejszego).
        d.line((18,598,382,598),fill='#777777',width=1)
        dates=daily.get('time',[])
        codes=daily.get('weather_code',[])
        highs=daily.get('temperature_2m_max',[])
        lows=daily.get('temperature_2m_min',[])
        weekdays=['Pon','Wt','Śr','Czw','Pt','Sob','Niedz']
        for i in range(4):
            j=i+1; x=50+i*100
            if i:d.line((i*100,608,i*100,695),fill='#555555',width=1)
            if j<len(dates):
                try: day=weekdays[datetime.fromisoformat(dates[j]).weekday()]
                except ValueError:day='—'
                self.draw_small_icon(d,weather_type(codes[j] if j<len(codes) else 2,True)[0],x,640)
                temp=f'{round(highs[j])}°' if j<len(highs) and highs[j] is not None else '—'
                low=f'{round(lows[j])}°' if j<len(lows) and lows[j] is not None else ''
                self.draw_centered(d,day,x,604,17,YELLOW,True)
                self.draw_centered(d,temp,x,665,20,WHITE,True)
                if low:self.draw_centered(d,low,x+28,673,11,'#aaaaaa')
            else:self.draw_centered(d,'—',x,625,19,WHITE)
        if self.error:centered(self.error[:32],469,13,YELLOW)
        # Przycisk odświeżania w miejscu wskazanym czerwonym prostokątem.
        # Mały symbol w prawym dolnym rogu sekcji opisu pogody.
        cx,cy=348,449
        d.arc((cx-8.8,cy-8.8,cx+8.8,cy+8.8),start=40,end=325,
              fill='#f3f5f8',width=2)
        d.polygon([(cx+8,cy-8.8),(cx+10.4,cy-1.6),(cx+2.4,cy-4)],
                  fill='#f3f5f8')
        self.tkimg=ImageTk.PhotoImage(im);self.canvas.delete('all');self.canvas.create_image(0,0,anchor='nw',image=self.tkimg)
        # Niewidoczny obszar klikalny 38×38 px; nie zmienia układu widżetu.
        self.canvas.create_rectangle(329,430,367,468,fill='',outline='',tags=('refresh_button',))
        self.canvas.tag_bind('refresh_button','<Button-1>',self.click_refresh)
        self.canvas.tag_bind('refresh_button','<Enter>',lambda e:self.canvas.configure(cursor='hand2'))
        self.canvas.tag_bind('refresh_button','<Leave>',lambda e:self.canvas.configure(cursor=''))

    def click_refresh(self,event=None):
        self.dismiss_menu()
        self.refresh()
        return 'break'

    def draw_centered(self,d,txt,x,y,size,color=WHITE,bold=False):
        f=font(size,bold);b=d.textbbox((0,0),txt,font=f)
        d.text((x-(b[2]-b[0])/2,y),txt,font=f,fill=color)

    def draw_detail_icon(self,d,index,x,y):
        # Ikony z referencji: wiatr, niebieska kropla, konturowa kropla, słońce.
        blue='#65bdf4'
        if index==0:
            for dy,length in ((-7,15),(0,22),(7,17)):
                yy=y+dy
                d.line((x-length,yy,x+8,yy),fill=WHITE,width=2)
                d.arc((x+3,yy-6,x+16,yy+6),270,90,fill=WHITE,width=2)
        elif index in (1,2):
            pts=[(x,y-12),(x-9,y+1),(x-8,y+8),(x-4,y+12),(x+4,y+12),(x+8,y+8),(x+9,y+1)]
            if index==1:d.polygon(pts,fill=blue)
            else:
                d.line(pts+[pts[0]],fill=blue,width=2,joint='curve')
                d.arc((x-4,y+1,x+5,y+9),15,155,fill=blue,width=2)
        else:
            d.ellipse((x-8,y-8,x+8,y+8),fill=YELLOW)
            for angle in range(0,360,45):
                a=math.radians(angle)
                d.line((x+math.cos(a)*11,y+math.sin(a)*11,x+math.cos(a)*15,y+math.sin(a)*15),fill=YELLOW,width=2)

    def draw_weather_art(self,d,kind,x,y,scale=1.0):
        """Spójne ikony markerowe: jedna sylwetka chmury, bez linii wewnętrznych."""
        def pt(dx,dy): return (round(x+dx*scale),round(y+dy*scale))
        def line(points,color,width):
            d.line([pt(*p) for p in points],fill=color,width=max(1,round(width*scale)),joint='curve')
        def sun(sx,sy,r):
            cx,cy=pt(sx,sy);rr=round(r*scale)
            d.ellipse((cx-rr,cy-rr,cx+rr,cy+rr),fill='#ffcc21',outline='#ffe88d',width=max(1,round(2*scale)))
            for deg in range(0,360,45):
                t=math.radians(deg)
                line([(sx+math.cos(t)*(r+7),sy+math.sin(t)*(r+7)),(sx+math.cos(t)*(r+17),sy+math.sin(t)*(r+17))],'#ffcc21',4)
        def cloud():
            # Rysowanie scalonej sylwetki daje gładki obrys bez nakładających się łuków.
            mask=Image.new('L',d._image.size,0);md=ImageDraw.Draw(mask)
            def ellipse(x1,y1,x2,y2):
                a=pt(x1,y1);b=pt(x2,y2);md.ellipse((*a,*b),fill=255)
            ellipse(-69,-6,-15,43)
            ellipse(-43,-33,28,43)
            ellipse(9,-8,72,43)
            a=pt(-65,16);b=pt(67,43)
            md.rounded_rectangle((*a,*b),radius=max(2,round(13*scale)),fill=255)
            from PIL import ImageChops
            edge=mask.filter(ImageFilter.MaxFilter(2*max(1,round(3*scale))+1))
            d._image.paste('#f7f7f7',(0,0),edge)
            d._image.paste('#9b9da3',(0,0),mask)
            # delikatne światło na górnej krawędzi
            line([(-49,0),(-41,-11),(-29,-14)],'#e5e8ee',2)
        if kind=='sun':sun(0,0,32);return
        if kind=='moon':
            cx,cy=pt(0,0);r=round(35*scale)
            d.ellipse((cx-r,cy-r,cx+r,cy+r),fill='#f4f0dc')
            # półksiężyc
            off=round(15*scale)
            d.ellipse((cx-r+off,cy-r-round(12*scale),cx+r+off,cy+r-round(12*scale)),fill='#252525')
            return
        if kind=='cloud':sun(35,-22,22)
        cloud()
        if kind in ('rain','storm'):
            for dx in (-42,0,42):line([(dx,54),(dx-11,72)],'#65bdf4',5)
        if kind=='snow':
            for dx in (-40,0,40):
                for angle in (0,60,120):
                    t=math.radians(angle)
                    line([(dx-8*math.cos(t),62-8*math.sin(t)),(dx+8*math.cos(t),62+8*math.sin(t))],WHITE,3)
        if kind=='storm':line([(8,45),(-8,65),(7,64),(-4,82)],'#ffcc21',6)
        if kind=='fog':
            for yy in (56,69):line([(-55,yy),(55,yy)],'#dedede',3)

    def draw_anime_3d_icon(self,d,kind,x,y,scale):
        """Przestrzenne ikony anime 3D inspirowane dostarczonym wzorem.
        Renderowane lokalnie, z miękkimi chmurami, słońcem i błękitnymi kroplami."""
        if not hasattr(self,'anime_icon_cache'):self.anime_icon_cache={}
        cache_key=(kind,round(scale,3))
        icon=self.anime_icon_cache.get(cache_key)
        if icon is None:
            import random
            S=3
            dim=200*S
            art=Image.new('RGBA',(dim,dim),(0,0,0,0))
            def xy(a,b):return (round((a+100)*S),round((b+100)*S))
            def ellipse(draw,b,fill,width=1,outline=None):
                draw.ellipse((*xy(b[0],b[1]),*xy(b[2],b[3])),
                             fill=fill,outline=outline,width=max(1,round(width*S)))
            def sun(cx,cy,r):
                glow=Image.new('RGBA',art.size,(0,0,0,0))
                gd=ImageDraw.Draw(glow,'RGBA')
                for radius,alpha in ((r+38,10),(r+29,22),(r+20,38),(r+12,58)):
                    ellipse(gd,(cx-radius,cy-radius,cx+radius,cy+radius),(255,181,22,alpha))
                glow=glow.filter(ImageFilter.GaussianBlur(7*S))
                art.alpha_composite(glow)
                rays=Image.new('RGBA',art.size,(0,0,0,0))
                rd=ImageDraw.Draw(rays,'RGBA')
                for angle in range(0,360,20):
                    t=math.radians(angle)
                    r1=r+5;r2=r+(28 if angle%40==0 else 18)
                    rd.polygon([xy(cx+math.cos(t-.055)*r1,cy+math.sin(t-.055)*r1),
                                xy(cx+math.cos(t)*r2,cy+math.sin(t)*r2),
                                xy(cx+math.cos(t+.055)*r1,cy+math.sin(t+.055)*r1)],
                               fill=(255,190,32,235))
                art.alpha_composite(rays.filter(ImageFilter.GaussianBlur(1.0*S)))
                disk=Image.new('RGBA',art.size,(0,0,0,0))
                dp=ImageDraw.Draw(disk,'RGBA')
                ellipse(dp,(cx-r,cy-r,cx+r,cy+r),(255,174,12,255))
                ellipse(dp,(cx-r+3,cy-r+3,cx+r-4,cy+r-5),(255,215,40,255))
                ellipse(dp,(cx-r+7,cy-r+5,cx+r-13,cy+4),(255,241,119,200))
                art.alpha_composite(disk)
            if kind=='sun':
                sun(0,0,31)
            elif kind=='moon':
                sun(0,0,29)
                # Złoty księżyc zamiast tarczy słońca.
                mask=Image.new('L',art.size,0)
                md=ImageDraw.Draw(mask)
                ellipse(md,(-34,-34,34,34),255)
                ellipse(md,(-8,-47,49,13),0)
                moon=Image.new('RGBA',art.size,(0,0,0,0))
                mp=ImageDraw.Draw(moon,'RGBA')
                ellipse(mp,(-34,-34,34,34),(255,237,184,255))
                moon.putalpha(mask)
                art=moon
            else:
                if kind in ('cloud','rain','storm'):
                    # Tak jak na wzorze: słońce wyłania się zza chmur.
                    sun(-27,-25,26 if kind!='cloud' else 25)
                # Miękki cień za chmurą.
                mask=Image.new('L',art.size,0)
                md=ImageDraw.Draw(mask)
                parts=[(-70,1,-23,44),(-57,-21,-1,46),(-32,-40,30,44),
                       (5,-29,56,43),(30,-6,72,42)]
                for box in parts:ellipse(md,box,255)
                md.rounded_rectangle((*xy(-65,16),*xy(67,43)),radius=16*S,fill=255)
                shadow=Image.new('RGBA',art.size,(0,0,0,0))
                shadow.putalpha(mask.filter(ImageFilter.GaussianBlur(7*S)).point(lambda v:round(v*.42)))
                art.alpha_composite(shadow,(0,7*S))
                # Głęboki granat na spodzie, chłodny błękit pośrodku, lawenda na szczycie.
                cloud=Image.new('RGBA',art.size,(0,0,0,0))
                pixels=cloud.load()
                for yy in range(36*S,150*S):
                    yy0=yy/S-100
                    t=max(0,min(1,(yy0+38)/87))
                    for xx in range(20*S,180*S):
                        xx0=xx/S-100
                        highlight=max(0,1-math.hypot((xx0+28)*.9,(yy0+23)*1.1)/73)
                        shade=max(0,1-math.hypot((xx0-30)*.7,(yy0-13)*.9)/75)
                        rr=int(max(25,min(255,230-119*t+29*highlight-31*shade)))
                        gg=int(max(35,min(255,237-105*t+23*highlight-17*shade)))
                        bb=int(max(65,min(255,255-62*t+8*highlight)))
                        pixels[xx,yy]=(rr,gg,bb,255)
                cloud.putalpha(mask)
                art.alpha_composite(cloud)
                # Puchate, wypukłe refleksy, delikatne światło od góry.
                highlights=Image.new('RGBA',art.size,(0,0,0,0))
                hp=ImageDraw.Draw(highlights,'RGBA')
                for b in [(-54,-16,-18,6),(-29,-32,5,-8),(4,-22,32,-3),
                          (30,-7,53,9),(-55,10,-31,26),(-17,0,14,20)]:
                    ellipse(hp,b,(244,248,255,87))
                art.alpha_composite(highlights.filter(ImageFilter.GaussianBlur(6*S)))
                # Osobne zaokrąglone fałdy chmury dają efekt 3D.
                folds=Image.new('RGBA',art.size,(0,0,0,0))
                fp=ImageDraw.Draw(folds,'RGBA')
                for b in [(-57,12,-28,33),(-31,9,4,32),(4,7,33,32),(33,13,57,34)]:
                    ellipse(fp,b,(64,122,185,60))
                art.alpha_composite(folds.filter(ImageFilter.GaussianBlur(4*S)))
                if kind in ('rain','storm'):
                    drops=Image.new('RGBA',art.size,(0,0,0,0))
                    dp=ImageDraw.Draw(drops,'RGBA')
                    for dx,dy in [(-51,51),(-28,58),(-3,50),(20,59),(45,50)]:
                        # Ukośne błękitne krople, grube i z jasnym połyskiem.
                        dp.line((xy(dx,dy),xy(dx-13,dy+23)),fill=(22,117,207,200),width=8*S)
                        dp.line((xy(dx-2,dy),xy(dx-14,dy+22)),fill=(45,190,255,255),width=5*S)
                        ellipse(dp,(dx-5,dy-1,dx-1,dy+4),(213,250,255,195))
                    art.alpha_composite(drops)
                if kind=='snow':
                    snow=Image.new('RGBA',art.size,(0,0,0,0))
                    sd=ImageDraw.Draw(snow,'RGBA')
                    for dx in (-42,-4,34):
                        for deg in (0,60,120):
                            t=math.radians(deg)
                            sd.line((xy(dx-9*math.cos(t),65-9*math.sin(t)),
                                     xy(dx+9*math.cos(t),65+9*math.sin(t))),
                                    fill=(241,250,255,255),width=3*S)
                    art.alpha_composite(snow)
                if kind=='storm':
                    bolt=Image.new('RGBA',art.size,(0,0,0,0))
                    bp=ImageDraw.Draw(bolt,'RGBA')
                    bp.polygon([xy(12,40),xy(-10,64),xy(3,64),xy(-7,84),
                                xy(26,54),xy(10,55)],fill=(255,211,39,255))
                    art.alpha_composite(bolt)
                if kind=='fog':
                    fog=Image.new('RGBA',art.size,(0,0,0,0))
                    fd=ImageDraw.Draw(fog,'RGBA')
                    for yy in (54,68):
                        fd.line((xy(-49,yy),xy(49,yy)),fill=(222,239,255,220),width=5*S)
                    art.alpha_composite(fog)
            side=max(10,round(200*scale))
            icon=art.resize((side,side),Image.Resampling.LANCZOS)
            self.anime_icon_cache[cache_key]=icon
        d._image.paste(icon,(round(x-icon.width/2),round(y-icon.height/2)),icon)

    def draw_small_icon(self,d,kind,x,y):
        if self.theme in ('landscape','city'):self.draw_anime_3d_icon(d,kind,x,y-4,0.31)
        else:self.draw_weather_art(d,kind,x,y-4,0.31)

    def draw_icon(self,d,kind):
        if self.theme in ('landscape','city'):self.draw_anime_3d_icon(d,kind,200,248,0.92)
        else:self.draw_weather_art(d,kind,200,248,1.25)

if __name__=='__main__':Widget()
