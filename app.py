import streamlit as st
import pandas as pd
import requests
import plotly.graph_objects as go
from datetime import datetime

# --- CONFIGURAÇÕES ---
st.set_page_config(page_title="MyInvest Pro", layout="wide", page_icon="📈")

# Substitua pelo seu token ou use st.secrets para maior segurança
BRAPI_TOKEN = "9eiTfvZsKatP12QcgSAS5W"

# --- FUNÇÕES DE API ---

@st.cache_data(ttl=3600)
def fetch_quote_data(tickers):
    if not tickers: return []
    tickers_str = ",".join(tickers)
    url = f"https://brapi.dev/api/quote/{tickers_str}?token={BRAPI_TOKEN}&fundamental=true"
    try:
        res = requests.get(url).json()
        return res.get('results', [])
    except:
        return []

@st.cache_data(ttl=86400)
def fetch_historical_and_bench(tickers, start_date):
    if not tickers: return pd.DataFrame()
    all_tickers = tickers + ["^BVSP"]
    tickers_str = ",".join(all_tickers)
    url = f"https://brapi.dev/api/quote/{tickers_str}?token={BRAPI_TOKEN}&range=2y&interval=1d"
    try:
        res = requests.get(url).json()
        df_prices = pd.DataFrame()
        for asset in res.get('results', []):
            symbol = asset['symbol']
            if 'historicalDataPrice' in asset:
                p = pd.DataFrame(asset['historicalDataPrice'])
                p['date'] = pd.to_datetime(p['date'], unit='s').dt.date
                p = p.set_index('date')[['close']].rename(columns={'close': symbol})
                df_prices = p if df_prices.empty else df_prices.join(p, how='outer')
        return df_prices.ffill()
    except:
        return pd.DataFrame()

@st.cache_data(ttl=86400)
def fetch_cdi(start_date):
    try:
        url = f"https://api.bcb.gov.br/dados/serie/bcdata.sgs.12/dados?formato=json&dataInicial={start_date.strftime('%d/%m/%Y')}&dataFinal={datetime.now().strftime('%d/%m/%Y')}"
        res = requests.get(url).json()
        df = pd.DataFrame(res)
        df['data'] = pd.to_datetime(df['data'], dayfirst=True).dt.date
        df['valor'] = pd.to_numeric(df['valor']) / 100
        df['CDI'] = (1 + df['valor']).cumprod() * 100
        return df.set_index('data')[['CDI']]
    except:
        return pd.DataFrame()

# --- LÓGICA DE PROCESSAMENTO ---

def process_b3(file):
    df = pd.read_excel(file)
    # Tenta localizar colunas mesmo que os nomes variem levemente
    df.columns = [c.strip() for c in df.columns]
    
    # Filtrar apenas Compra/Venda (ajustado para ser mais flexível)
    df = df[df['Movimentação'].str.contains('Compra|Venda', case=False, na=False)].copy()
    
    df['ticker'] = df['Produto'].apply(lambda x: str(x).split(" - ")[0].strip())
    df['Data'] = pd.to_datetime(df['Data']).dt.date
    df['qtd_mod'] = df.apply(lambda x: x['Quantidade'] if 'Compra' in x['Movimentação'] else -x['Quantidade'], axis=1)
    return df

# --- INTERFACE ---

st.title("📊 MyInvest - Carteira B3")
st.markdown("Acompanhe seu patrimônio, rentabilidade e dividendos.")

file = st.sidebar.file_uploader("Upload Excel B3 (Movimentação)", type=["xlsx"])

if file:
    df_mov = process_b3(file)
    tickers = sorted(df_mov['ticker'].unique().tolist())
    primeiro_aporte = df_mov['Data'].min()
    
    with st.spinner("Sincronizando dados..."):
        api_data = fetch_quote_data(tickers)
        
        # Posição Atual
        posicao = []
        for t in tickers:
            qtd = df_mov[df_mov['ticker'] == t]['qtd_mod'].sum()
            if qtd > 0:
                price = next((x['regularMarketPrice'] for x in api_data if x['symbol'] == t), 0)
                posicao.append({'Ativo': t, 'Qtd': qtd, 'Preço': price, 'Total': qtd * price})
        
        df_pos = pd.DataFrame(posicao)

        tab1, tab2, tab3 = st.tabs(["🏠 Dashboard", "📈 Rentabilidade", "💰 Dividendos"])

        with tab1:
            total = df_pos['Total'].sum() if not df_pos.empty else 0
            st.metric("Patrimônio Total", f"R$ {total:,.2f}")
            if not df_pos.empty:
                fig_p = go.Figure(data=[go.Pie(labels=df_pos['Ativo'], values=df_pos['Total'], hole=.4)])
                st.plotly_chart(fig_p, use_container_width=True)
                st.dataframe(df_pos, hide_index=True, use_container_width=True)

        with tab2:
            df_hist = fetch_historical_and_bench(tickers, primeiro_aporte)
            df_cdi = fetch_cdi(primeiro_aporte)
            
            if not df_hist.empty:
                h_port = pd.DataFrame(index=df_hist.index)
                for t in tickers:
                    q = df_mov[df_mov['ticker'] == t].groupby('Data')['qtd_mod'].sum().reindex(df_hist.index).fillna(0).cumsum()
                    if t in df_hist.columns:
                        h_port[t] = q * df_hist[t]
                
                h_port['Carteira'] = (h_port.sum(axis=1) / h_port.sum(axis=1).iloc[0]) * 100
                h_port['IBOV'] = (df_hist['^BVSP'] / df_hist['^BVSP'].iloc[0]) * 100
                h_port = h_port.join(df_cdi).ffill()
                
                fig_r = go.Figure()
                fig_r.add_trace(go.Scatter(x=h_port.index, y=h_port['Carteira'], name="Carteira", line=dict(color='#00CC96')))
                fig_r.add_trace(go.Scatter(x=h_port.index, y=h_port['IBOV'], name="IBOV", line=dict(color='white', dash='dot')))
                fig_r.add_trace(go.Scatter(x=h_port.index, y=h_port['CDI'], name="CDI", line=dict(color='#FFAA00', dash='dash')))
                st.plotly_chart(fig_r, use_container_width=True)

        with tab3:
            st.subheader("Próximos Dividendos")
            div_list = []
            for asset in api_data:
                symbol = asset['symbol']
                for d in asset.get('dividendsData', {}).get('cashDividends', []):
                    pay_date = pd.to_datetime(d['paymentDate']).date()
                    com_date = pd.to_datetime(d['assetIssued']).date()
                    if pay_date >= datetime.now().date():
                        qtd_com = df_mov[(df_mov['ticker'] == symbol) & (df_mov['Data'] <= com_date)]['qtd_mod'].sum()
                        if qtd_com > 0:
                            div_list.append({'Ativo': symbol, 'Data Com': com_date, 'Pagamento': pay_date, 'Valor': d['rate'] * qtd_com})
            
            if div_list:
                df_div = pd.DataFrame(div_list).sort_values('Pagamento')
                st.write(f"Total a receber: R$ {df_div['Valor'].sum():,.2f}")
                st.table(df_div)
            else:
                st.info("Nenhum dividendo provisionado encontrado.")
else:
    st.info("Faça o upload do seu relatório 'Movimentação' da B3 no menu lateral.")