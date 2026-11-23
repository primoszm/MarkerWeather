import json, math, os, threading, urllib.parse, urllib.request, tkinter as tk, time
from datetime import datetime
from PIL import Image, ImageDraw, ImageFont, ImageTk, ImageFilter

W,H=400,700
WHITE='#f7f7f7'; YELLOW='#ffc928'
BASE=os.path.dirname(os.path.abspath(__file__))
CONFIG=os.path.join(os.path.expanduser('~'),'.marker_weather.json')

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
        self.city='Gdańsk';self.lat=54.352;self.lon=18.6466;self.data=None;self.error='';self.busy=False;self.top=False;self.opacity=100;self.theme='standard';self.old_kind=None;self.transition_start=0;self.transition_from=None;self.transition_to=None;self.last_kind=None
        try:
            with open(CONFIG,encoding='utf8') as f:
                c=json.load(f);self.city=c.get('city',self.city);self.lat=c.get('lat',self.lat);self.lon=c.get('lon',self.lon);self.opacity=max(30,min(100,int(c.get('opacity',100))));self.theme=c.get('theme','standard') if c.get('theme','standard') in ('standard','graphic') else 'standard'
        except (OSError,ValueError,TypeError):pass
        self.root.attributes('-alpha',self.opacity/100)
        self.root.bind('<ButtonPress-1>',self.drag_start);self.root.bind('<B1-Motion>',self.drag_move)
        self.root.bind('<Button-3>',self.menu);self.root.bind('<Escape>',lambda e:self.root.destroy())
        self.root.bind('<Double-Button-1>',lambda e:self.change_city())
        self.tkimg=None;self.tick();self.refresh();self.root.mainloop()
    def drag_start(self,e):self.dx=e.x_root-self.root.winfo_x();self.dy=e.y_root-self.root.winfo_y()
    def drag_move(self,e):self.root.geometry(f'+{e.x_root-self.dx}+{e.y_root-self.dy}')
    def menu(self,e):
        m=tk.Menu(self.root,tearoff=0);m.add_command(label='Zmień miasto',command=self.change_city);m.add_command(label='Odśwież pogodę',command=self.refresh)
        appearance=tk.Menu(m,tearoff=0)
        appearance.add_command(label=('✓ ' if self.theme=='standard' else '   ')+'Standardowy — ciemny gradient',command=lambda:self.set_theme('standard'))
        appearance.add_command(label=('✓ ' if self.theme=='graphic' else '   ')+'Graficzny — pogoda w tle',command=lambda:self.set_theme('graphic'))
        m.add_cascade(label='Wygląd aplikacji',menu=appearance)
        m.add_command(label='Zawsze na wierzchu: '+('TAK' if self.top else 'NIE'),command=self.toggle_top);m.add_command(label='Przezroczystość…',command=self.opacity_dialog);m.add_separator();m.add_command(label='Zamknij',command=self.root.destroy)
        m.tk_popup(e.x_root,e.y_root)
    def set_theme(self,theme):
        if theme not in ('standard','graphic'):return
        if theme!=self.theme:
            self.theme=theme;self.save_config();self.render()
    def toggle_top(self):self.top=not self.top;self.root.attributes('-topmost',self.top)
    def save_config(self):
        try:
            with open(CONFIG,'w',encoding='utf8') as f:
                json.dump({'city':self.city,'lat':self.lat,'lon':self.lon,'opacity':self.opacity,'theme':self.theme},f,ensure_ascii=False)
        except OSError:pass
    def opacity_dialog(self):
        dlg=tk.Toplevel(self.root);dlg.title('Przezroczystość');dlg.geometry('320x145');dlg.resizable(False,False)
        dlg.attributes('-topmost',True)
        lbl=tk.Label(dlg,text=f'Widoczność okna: {self.opacity}%');lbl.pack(pady=(12,0))
        def update(value):
            self.opacity=int(float(value));self.root.attributes('-alpha',self.opacity/100)
            lbl.configure(text=f'Widoczność okna: {self.opacity}%');self.save_config()
        scale=tk.Scale(dlg,from_=30,to=100,orient='horizontal',resolution=1,length=275,showvalue=False,command=update)
        scale.set(self.opacity);scale.pack()
        tk.Button(dlg,text='Gotowe',command=dlg.destroy).pack(pady=3)
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
        self.save_config()
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
        self.render()
    def tick(self):
        self.render()
        active=self.transition_from is not None and time.monotonic()-self.transition_start<1.5
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

    def render(self):
        current=self.data.get('current',{}) if self.data else {}
        kind,_=weather_type(current.get('weather_code',2),current.get('is_day',1))
        im=self.make_background(kind,current.get('is_day',1)) if self.theme=='graphic' else self.make_standard_background()
        d=ImageDraw.Draw(im)
        def centered(txt,y,size,color=WHITE,bold=False):
            f=font(size,bold);b=d.textbbox((0,0),txt,font=f);d.text(((W-(b[2]-b[0]))/2,y),txt,font=f,fill=color,stroke_width=0)
        now=datetime.now();centered(now.strftime('%H:%M'),24,82,WHITE,True)
        centered(self.city,145,27)
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
            centered(f"{round(current['temperature_2m'])}°C",350,76,WHITE,True)
        else:centered('—°C',350,76,WHITE,True)
        d.arc((85,435,315,455),180,355,fill=YELLOW,width=5)
        centered(desc,452,21)
        d.line((18,507,382,507),fill='#777777',width=1)
        wind=round(current.get('wind_speed_10m',0));hum=round(current.get('relative_humidity_2m',0))
        chance=daily.get('precipitation_probability_max',[None])[0]
        sunrise=daily.get('sunrise',[''])[0][-5:];sunset=daily.get('sunset',[''])[0][-5:]
        vals=[('WIATR',f'{wind} km/h' if self.data else '—'),('OPADY',f'{chance}%' if chance is not None else '—'),('WILG.',f'{hum}%' if self.data else '—'),('SŁOŃCE',f'{sunrise}\n{sunset}' if sunrise else '—')]
        for i,(lab,val) in enumerate(vals):
            x=i*100+50
            if i:d.line((i*100,521,i*100,584),fill='#777777',width=1)
            f=font(13,True);b=d.textbbox((0,0),lab,font=f);d.text((x-(b[2]-b[0])/2,520),lab,font=f,fill=YELLOW)
            for j,line in enumerate(val.split('\n')):
                f2=font(15,True);b2=d.textbbox((0,0),line,font=f2);d.text((x-(b2[2]-b2[0])/2,544+j*20),line,font=f2,fill=WHITE)
        # Prognoza na kolejne cztery dni (bez dnia dzisiejszego).
        d.line((18,593,382,593),fill='#777777',width=1)
        dates=daily.get('time',[])
        codes=daily.get('weather_code',[])
        highs=daily.get('temperature_2m_max',[])
        lows=daily.get('temperature_2m_min',[])
        weekdays=['Pon','Wt','Śr','Czw','Pt','Sob','Niedz']
        for i in range(4):
            j=i+1; x=50+i*100
            if i:d.line((i*100,610,i*100,688),fill='#555555',width=1)
            if j<len(dates):
                try: day=weekdays[datetime.fromisoformat(dates[j]).weekday()]
                except ValueError:day='—'
                self.draw_small_icon(d,weather_type(codes[j] if j<len(codes) else 2,True)[0],x,642)
                temp=f'{round(highs[j])}°' if j<len(highs) and highs[j] is not None else '—'
                low=f'{round(lows[j])}°' if j<len(lows) and lows[j] is not None else ''
                self.draw_centered(d,day,x,601,17,YELLOW,True)
                self.draw_centered(d,temp,x,663,20,WHITE,True)
                if low:self.draw_centered(d,low,x+28,670,11,'#aaaaaa')
            else:self.draw_centered(d,'—',x,625,19,WHITE)
        if self.error:centered(self.error[:32],486,13,YELLOW)
        self.tkimg=ImageTk.PhotoImage(im);self.canvas.delete('all');self.canvas.create_image(0,0,anchor='nw',image=self.tkimg)
    def draw_centered(self,d,txt,x,y,size,color=WHITE,bold=False):
        f=font(size,bold);b=d.textbbox((0,0),txt,font=f)
        d.text((x-(b[2]-b[0])/2,y),txt,font=f,fill=color)

    def draw_small_icon(self,d,kind,x,y):
        # Symbole wektorowe zamiast emoji — działają niezależnie od czcionki.
        if kind in ('sun','cloud'):
            sx=x if kind=='sun' else x+11;sy=y-5
            d.ellipse((sx-10,sy-10,sx+10,sy+10),fill=YELLOW)
            for a in range(0,360,45):
                t=math.radians(a)
                d.line((sx+math.cos(t)*14,sy+math.sin(t)*14,sx+math.cos(t)*18,sy+math.sin(t)*18),fill=YELLOW,width=2)
            if kind=='sun':return
        if kind=='moon':
            d.ellipse((x-12,y-16,x+12,y+8),fill='#f1edcf')
            d.ellipse((x-3,y-20,x+15,y-2),fill='#252525')
            return
        d.ellipse((x-22,y-9,x-2,y+8),fill='#9b9da3',outline=WHITE,width=2)
        d.ellipse((x-10,y-17,x+13,y+9),fill='#9b9da3',outline=WHITE,width=2)
        d.ellipse((x+3,y-8,x+23,y+9),fill='#9b9da3',outline=WHITE,width=2)
        d.rounded_rectangle((x-21,y,x+22,y+10),radius=5,fill='#9b9da3',outline=WHITE,width=2)
        if kind in ('rain','storm'):
            for dx in (-12,0,12):d.line((x+dx,y+14,x+dx-4,y+23),fill='#72b9ef',width=2)
        if kind=='snow':
            for dx in (-12,0,12):
                d.line((x+dx,y+14,x+dx,y+22),fill=WHITE,width=2)
                d.line((x+dx-3,y+18,x+dx+3,y+18),fill=WHITE,width=2)
        if kind=='storm':d.line((x+2,y+12,x-5,y+24,x+3,y+22),fill=YELLOW,width=3)
        if kind=='fog':
            for yy in (y+15,y+21):d.line((x-19,yy,x+19,yy),fill='#cccccc',width=2)

    def draw_icon(self,d,kind):
        cx,cy=200,267
        def sun(x,y,r):
            d.ellipse((x-r,y-r,x+r,y+r),fill=YELLOW,outline='#fff0a3',width=3)
            for a in range(0,360,45):
                t=math.radians(a);d.line((x+math.cos(t)*(r+9),y+math.sin(t)*(r+9),x+math.cos(t)*(r+23),y+math.sin(t)*(r+23)),fill=YELLOW,width=5)
        def cloud(x,y):
            d.ellipse((x-100,y-10,x-20,y+56),fill='#9b9da3',outline=WHITE,width=5)
            d.ellipse((x-50,y-40,x+38,y+55),fill='#9b9da3',outline=WHITE,width=5)
            d.ellipse((x+10,y-5,x+104,y+56),fill='#9b9da3',outline=WHITE,width=5)
            d.rounded_rectangle((x-92,y+22,x+95,y+57),radius=17,fill='#9b9da3',outline=WHITE,width=4)
        if kind=='sun':sun(cx,cy,51)
        elif kind=='moon':
            d.ellipse((cx-57,cy-57,cx+57,cy+57),fill='#f3f3d6');d.ellipse((cx-22,cy-80,cx+73,cy+18),fill='#242425')
        else:
            if kind=='cloud':sun(cx+60,cy-43,38)
            cloud(cx,cy)
            if kind in ('rain','storm'):
                for x in (135,190,245):d.line((x,cy+68,x-13,cy+91),fill='#72b9ef',width=5)
            if kind=='snow':
                for x in (140,200,260):d.text((x,cy+65),'✳',font=font(26),fill=WHITE)
            if kind=='storm':d.line((208,cy+62,185,cy+99,211,cy+95,194,cy+120),fill=YELLOW,width=7)
            if kind=='fog':
                for y in (cy+75,cy+90):d.line((95,y,305,y),fill='#c3c3c3',width=4)

if __name__=='__main__':Widget()
