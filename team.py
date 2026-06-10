import streamlit as st
import pandas as pd
import requests
import plotly.express as px
import plotly.graph_objects as go

# -----------------------------------------------------------------------------
# 1. APP CONFIG & INITIALIZATION
# -----------------------------------------------------------------------------
st.set_page_config(page_title="SSL Team Tracker & Analytics", layout="wide")
st.title("⚽ SSL Team Tracker & GM Dashboard")
st.markdown("---")

API_URL = "https://api.simulationsoccer.com/player/getAllPlayers?active=true"

ORG_MAPPING = {
    "CA Buenos Aires": {"Major": "CA Buenos Aires", "Minor": "Athênai F.C."},
    "Hollywood FC": {"Major": "Hollywood FC", "Minor": "F.C. Kaapstad"},
    "A.C. Romana": {"Major": "A.C. Romana", "Minor": "Inter London"},
    "Reykjavik United": {"Major": "Reykjavik United", "Minor": "North Shore United"},
    "Shanghai Dragons FC": {"Major": "Shanghai Dragons FC", "Minor": "Rapid Magyar SC"},
    "Xelajú Cósmico FC": {"Major": "Xelajú Cósmico FC", "Minor": "AF Masques Sacrés"},
    "Tokyo S.C.": {"Major": "Tokyo S.C.", "Minor": "Cairo City"},
    "CF Catalunya": {"Major": "CF Catalunya", "Minor": "Seoul MFC"},
    "União São Paulo": {"Major": "União São Paulo", "Minor": "AS Paris"},
    "Schwarzwälder FV": {"Major": "Schwarzwälder FV", "Minor": "Montréal United"},
    "CD Tenochtitlan": {"Major": "CD Tenochtitlan", "Minor": "Krung Thep FC"},
    "Liffeyside Celtic FC": {"Major": "Liffeyside Celtic FC", "Minor": "CS Rova Mpanjaka"}
}

SHEET_TO_API_MAPPING = {
    "Club Atlètico Buenos Aires": "CA Buenos Aires",
    "Hollywood Football Club": "Hollywood FC",
    "Athletice Clava Romana": "A.C. Romana",
    "Reykjavik United": "Reykjavik United",
    "Shanghai Dragons": "Shanghai Dragons FC",
    "Xelajú Cósmico Fùtbol Club": "Xelajú Cósmico FC",
    "Tokyo Sports Club": "Tokyo S.C.",
    "Club de Futbol Catalunya": "CF Catalunya",
    "União São Paulo": "União São Paulo",
    "Schwarzwälder Fußballverein": "Schwarzwälder FV",
    "Club Deportivo Tenochtitlan": "CD Tenochtitlan",
    "Liffeyside Celtic Football Club": "Liffeyside Celtic FC"
}

TEAM_TO_ORG = {}
for org, teams in ORG_MAPPING.items():
    TEAM_TO_ORG[teams["Major"]] = {"org": org, "type": "Major"}
    TEAM_TO_ORG[teams["Minor"]] = {"org": org, "type": "Minor"}

POSITION_GROUPS = {
    "Attack": ["pos_st", "pos_lam", "pos_ram", "pos_cam"],
    "Midfield": ["pos_lm", "pos_cm", "pos_rm", "pos_cdm"],
    "Defense": ["pos_ld", "pos_lwb", "pos_rd", "pos_rwb", "pos_cd"],
    "Goalkeeper": ["pos_gk"]
}

CORE_ATTRIBUTES = [
    "acceleration", "agility", "balance", "jumping reach", "natural fitness", "pace", "stamina", "strength",
    "corners", "crossing", "dribbling", "finishing", "first touch", "free kick", "heading", "long shots",
    "long throws", "marking", "passing", "penalty taking", "tackling", "technique", "aggression", "anticipation",
    "bravery", "composure", "concentration", "decisions", "determination", "flair", "leadership", "off the ball",
    "positioning", "teamwork", "vision", "work rate"
]

# -----------------------------------------------------------------------------
# 2. DATA CACHING & PROCESSING (API)
# -----------------------------------------------------------------------------
@st.cache_data(ttl=600)
def load_and_process_data():
    try:
        response = requests.get(API_URL)
        response.raise_for_status()
        data = response.json()
    except Exception as e:
        st.error(f"Failed to fetch data from API: {e}")
        return pd.DataFrame()

    df = pd.DataFrame(data)
    df['tpe'] = pd.to_numeric(df['tpe'], errors='coerce').fillna(0)
    df['bankBalance'] = pd.to_numeric(df['bankBalance'], errors='coerce').fillna(0)
    
    df['assigned_org'] = df['team'].apply(lambda x: TEAM_TO_ORG.get(x, {}).get('org', 'Unknown'))
    df['league_tier'] = df['team'].apply(lambda x: TEAM_TO_ORG.get(x, {}).get('type', 'Unknown'))
    df = df[df['assigned_org'] != 'Unknown']
    
    df['season_num'] = df['class'].astype(str).str.extract(r'(\d+)').astype(float)
    df['timesregressed'] = pd.to_numeric(df['timesregressed'], errors='coerce').fillna(0)
    
    return df

df_players = load_and_process_data()

if df_players.empty:
    st.warning("No data available to display from the API.")
    st.stop()

# -----------------------------------------------------------------------------
# 3. GOOGLE SHEETS INTEGRATION & TABLE HUNTER
# -----------------------------------------------------------------------------
SPREADSHEET_ID = "1dlJLL85csDV8HXaig8dtZQNgmG9YeAJSS3eeM-nhocA"
LEADERBOARD_GID = "1702210962" 

@st.cache_data(ttl=600)
def load_google_sheet(gid):
    try:
        url = f"https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}/export?format=csv&gid={gid}"
        df = pd.read_csv(url)
        return df
    except Exception as e:
        return pd.DataFrame()

df_leaderboard = load_google_sheet(LEADERBOARD_GID)

history_df = pd.DataFrame()
tpe_name = 'TPE'

if not df_leaderboard.empty:
    team_idx, season_idx, tpe_idx = -1, -1, -1
    found_start_row = -1
    
    for index, row in df_leaderboard.iterrows():
        row_vals = [str(x).strip().lower() for x in row.values]
        
        if 'top xi avg' in row_vals:
            tpe_idx = row_vals.index('top xi avg')
            for i in range(tpe_idx - 1, -1, -1):
                if row_vals[i] == 'season' and season_idx == -1: season_idx = i
                elif row_vals[i] == 'team' and team_idx == -1: team_idx = i
            
            if team_idx != -1 and season_idx != -1:
                tpe_name = 'Top XI Avg TPE'
                found_start_row = index
                break
                
        elif 'avg tpe' in row_vals:
            tpe_idx = row_vals.index('avg tpe')
            for i in range(tpe_idx - 1, -1, -1):
                if row_vals[i] == 'season' and season_idx == -1: season_idx = i
                elif row_vals[i] == 'team' and team_idx == -1: team_idx = i
                    
            if team_idx != -1 and season_idx != -1:
                tpe_name = 'Avg TPE'
                found_start_row = index
                break
    
    if found_start_row != -1:
        extracted_data = []
        for i in range(found_start_row + 1, len(df_leaderboard)):
            data_row = df_leaderboard.iloc[i]
            try:
                team_val = data_row.iloc[team_idx]
                season_val = data_row.iloc[season_idx]
                tpe_val = data_row.iloc[tpe_idx]
                
                if pd.notna(team_val) and str(team_val).strip() != '' and str(team_val).strip().lower() != 'team':
                    extracted_data.append({'Team': team_val, 'Season': season_val, 'TPE_Value': tpe_val})
            except IndexError:
                continue
        
        history_df = pd.DataFrame(extracted_data)
        history_df['TPE_Value'] = pd.to_numeric(history_df['TPE_Value'], errors='coerce')
        history_df['Season'] = pd.to_numeric(history_df['Season'], errors='coerce')
        history_df = history_df.dropna(subset=['Season', 'TPE_Value'])
        
        if not history_df.empty:
            history_df['API_Team'] = history_df['Team'].map(SHEET_TO_API_MAPPING).fillna(history_df['Team'])

# -----------------------------------------------------------------------------
# 4. GLOBAL SIDEBAR FILTERS
# -----------------------------------------------------------------------------
st.sidebar.header("Global Filters")

group_mode = st.sidebar.radio("Entity Grouping", ["Individual Teams", "Combined Franchise Orgs"], index=0)
group_col = 'team' if group_mode == "Individual Teams" else 'assigned_org'

tier_filter = st.sidebar.radio("League Tier", ["Both", "Majors Only", "Minors Only"], index=0)
roster_filter = st.sidebar.radio("Roster Inclusion", ["Top 11 Players (Starting XI)", "All Players"], index=0)
metric_toggle = st.sidebar.radio("Metric Display Mode", ["Average", "Total"], index=0)

if tier_filter == "Majors Only":
    df_active = df_players[df_players['league_tier'] == 'Major']
elif tier_filter == "Minors Only":
    df_active = df_players[df_players['league_tier'] == 'Minor']
else:
    df_active = df_players.copy()

if roster_filter == "Top 11 Players (Starting XI)":
    df_active = df_active.sort_values(by='tpe', ascending=False).groupby(group_col).head(11).reset_index(drop=True)

# List used for dropdowns in tabs 5 and 6
all_entities_filtered = sorted([str(t) for t in df_active[group_col].dropna().unique() if str(t).strip() != ''])

# -----------------------------------------------------------------------------
# 5. HELPER FUNCTIONS
# -----------------------------------------------------------------------------
def build_positional_matrix(df_scope, metric, g_col):
    entities = df_scope[g_col].unique()
    data = []
    
    for e in entities:
        team_df = df_scope[df_scope[g_col] == e]
        team_stats = {"Entity Name": e}
        team_stats["Overall TPE"] = team_df['tpe'].mean() if metric == "Average" else team_df['tpe'].sum()
            
        for group, cols in POSITION_GROUPS.items():
            mask = team_df[cols].apply(lambda row: any(row >= 15), axis=1)
            group_df = team_df[mask]
            if not group_df.empty:
                team_stats[f"{group} TPE"] = group_df['tpe'].mean() if metric == "Average" else group_df['tpe'].sum()
            else:
                team_stats[f"{group} TPE"] = 0
        data.append(team_stats)
        
    res_df = pd.DataFrame(data)
    if not res_df.empty:
        res_df = res_df.sort_values(by="Overall TPE", ascending=False).reset_index(drop=True)
    return res_df

def calculate_positional_averages(df_scope, metric):
    pos_data = {}
    for group, columns in POSITION_GROUPS.items():
        mask = df_scope[columns].apply(lambda row: any(row >= 15), axis=1)
        matching_players = df_scope[mask]
        
        if not matching_players.empty:
            val = matching_players['tpe'].mean() if metric == "Average" else matching_players['tpe'].sum()
            pos_data[group] = {f"{metric} TPE": round(val, 1), "Count": len(matching_players)}
        else:
            pos_data[group] = {f"{metric} TPE": 0, "Count": 0}
    return pd.DataFrame(pos_data).T

# -----------------------------------------------------------------------------
# 6. MAIN INTERFACE TABS
# -----------------------------------------------------------------------------
tab_overview, tab_lifecycle, tab_matrix, tab_finance, tab_roster, tab_h2h, tab_history, tab_leaderboard = st.tabs([
    "📊 League Overview", 
    "⏳ Lifecycle Quadrants",
    "🧮 Positional TPE Matrix", 
    "💰 Financial Analysis",
    "📋 Team Deep Dive", 
    "⚔️ Head-to-Head",
    "📈 Historical Trends",
    "🏆 Live Leaderboard & Peaks"
])

# --- TAB 1: LEAGUE OVERVIEW ---
with tab_overview:
    st.header(f"League-Wide TPE Distribution ({roster_filter})")
    team_order = df_active.groupby(group_col)['tpe'].mean().sort_values(ascending=False).index.tolist()
    fig_scatter = px.scatter(
        df_active, x=group_col, y='tpe', color=group_col,
        hover_data=['name', 'team', 'class', 'position'],
        title=f"Player TPE Across {group_mode} (Sorted by Average TPE)",
        labels={group_col: 'Entity', 'tpe': 'Player TPE'},
        category_orders={group_col: team_order}
    )
    fig_scatter.update_layout(xaxis_tickangle=-45, showlegend=False)
    st.plotly_chart(fig_scatter, use_container_width=True)

# --- TAB 2: LIFECYCLE QUADRANTS ---
with tab_lifecycle:
    st.header(f"Team Lifecycle & Development ({roster_filter})")
    st.markdown("X-Axis: Average Draft Class (Older on right) | Y-Axis: Current TPE.")
    lifecycle_df = df_active.groupby(group_col).agg(Avg_TPE=('tpe', 'mean' if metric_toggle == "Average" else 'sum'), Avg_Season=('season_num', 'mean')).dropna().reset_index()

    if not lifecycle_df.empty:
        med_tpe = lifecycle_df['Avg_TPE'].median()
        med_season = lifecycle_df['Avg_Season'].median()
        fig_quad = px.scatter(lifecycle_df, x='Avg_Season', y='Avg_TPE', text=group_col, color=group_col)
        fig_quad.update_xaxes(autorange="reversed")
        fig_quad.add_hline(y=med_tpe, line_dash="dash", line_color="rgba(255,255,255,0.3)")
        fig_quad.add_vline(x=med_season, line_dash="dash", line_color="rgba(255,255,255,0.3)")
        fig_quad.update_traces(textposition='top center', marker=dict(size=12))
        fig_quad.update_layout(showlegend=False, height=600)
        st.plotly_chart(fig_quad, use_container_width=True)

# --- TAB 3: POSITIONAL MATRIX ---
with tab_matrix:
    st.header(f"Positional Breakdown ({metric_toggle} TPE)")
    matrix_df = build_positional_matrix(df_active, metric_toggle, group_col)
    st.dataframe(matrix_df.style.format(precision=1).background_gradient(cmap='viridis', subset=matrix_df.columns[1:]), use_container_width=True, hide_index=True)

# --- TAB 4: FINANCIALS ---
with tab_finance:
    st.header("Financial Overview")
    league_summary = df_active.groupby(group_col).agg(Total_Bank=('bankBalance', 'sum'), Avg_Bank=('bankBalance', 'mean')).round(0).reset_index()
    fig_bank = px.bar(league_summary.sort_values(by="Total_Bank" if metric_toggle == "Total" else "Avg_Bank", ascending=False), x=group_col, y="Total_Bank" if metric_toggle == "Total" else "Avg_Bank", text="Total_Bank" if metric_toggle == "Total" else "Avg_Bank")
    fig_bank.update_traces(texttemplate='€%{text:,.0f}', textposition='outside')
    fig_bank.update_layout(xaxis_tickangle=-45)
    st.plotly_chart(fig_bank, use_container_width=True)

# --- TAB 5: DETAILED ROSTER ANALYSIS ---
with tab_roster:
    st.header("Individual Roster Deep Dive")
    if len(all_entities_filtered) > 0:
        selected_target = st.selectbox("Select Entity to Inspect", all_entities_filtered)
        df_team_specific = df_active[df_active[group_col] == selected_target]
        col_left, col_right = st.columns([1, 2])
        with col_left:
            pos_df = calculate_positional_averages(df_team_specific, metric_toggle)
            st.dataframe(pos_df, use_container_width=True)
        with col_right:
            attr_means = df_team_specific[CORE_ATTRIBUTES].mean().round(2).reset_index()
            attr_means.columns = ['Attribute', 'Average Value']
            fig_radar = go.Figure(go.Scatterpolar(r=attr_means['Average Value'], theta=attr_means['Attribute'], fill='toself'))
            st.plotly_chart(fig_radar, use_container_width=True)
    else:
        st.info("No entities available for current filters.")

# --- TAB 6: HEAD-TO-HEAD ---
with tab_h2h:
    st.header(f"⚔️ Tactical Matchup ({metric_toggle})")
    if len(all_entities_filtered) > 1:
        col_sel1, col_sel2 = st.columns(2)
        with col_sel1: 
            team_a = st.selectbox("Select Blue Corner", all_entities_filtered, index=0)
        with col_sel2: 
            team_b = st.selectbox("Select Red Corner", all_entities_filtered, index=min(1, len(all_entities_filtered)-1))
            
        df_a = df_active[df_active[group_col] == team_a]
        df_b = df_active[df_active[group_col] == team_b]
        
        pos_a = calculate_positional_averages(df_a, metric_toggle)
        pos_b = calculate_positional_averages(df_b, metric_toggle)
        
        comparison_df = pd.DataFrame({
            f"{team_a} {metric_toggle} TPE": pos_a[f"{metric_toggle} TPE"],
            f"{team_a} Count": pos_a["Count"],
            f"{team_b} {metric_toggle} TPE": pos_b[f"{metric_toggle} TPE"],
            f"{team_b} Count": pos_b["Count"]
        })
        
        st.subheader("Side-by-Side Positional Breakdown")
        st.dataframe(comparison_df, use_container_width=True)
        
        st.subheader("Direct Attribute Overlay")
        attr_a = df_a[CORE_ATTRIBUTES].mean().round(2)
        attr_b = df_b[CORE_ATTRIBUTES].mean().round(2)
        
        fig_h2h_radar = go.Figure()
        fig_h2h_radar.add_trace(go.Scatterpolar(r=attr_a.values, theta=CORE_ATTRIBUTES, fill='toself', name=team_a, fillcolor='rgba(31, 119, 180, 0.2)', line=dict(color='blue')))
        fig_h2h_radar.add_trace(go.Scatterpolar(r=attr_b.values, theta=CORE_ATTRIBUTES, fill='toself', name=team_b, fillcolor='rgba(214, 39, 40, 0.2)', line=dict(color='red')))
        fig_h2h_radar.update_layout(polar=dict(radialaxis=dict(visible=True, range=[0, 20])))
        st.plotly_chart(fig_h2h_radar, use_container_width=True)
    else:
        st.info("Not enough entities to compare based on your current filters.")

# --- TAB 7: HISTORICAL TRENDS ---
with tab_history:
    st.header("📈 Historical Franchise Momentum")
    if not history_df.empty:
        all_teams = history_df['API_Team'].dropna().unique().tolist()
        default_selection = all_teams[:4] if len(all_teams) >= 4 else all_teams
        selected_teams = st.multiselect("Select Franchises to Compare:", all_teams, default=default_selection)
        
        if selected_teams:
            filtered_history = history_df[history_df['API_Team'].isin(selected_teams)].sort_values(by='Season')
            fig_timeline = px.line(
                filtered_history, x='Season', y='TPE_Value', color='API_Team', markers=True,
                title=f"Timeline of Roster Growth ({tpe_name})",
                labels={"Season": "League Season", "TPE_Value": "Historical TPE", "API_Team": "Franchise"}
            )
            fig_timeline.update_layout(hovermode="x unified")
            st.plotly_chart(fig_timeline, use_container_width=True)
        else:
            st.info("Please select at least one team from the dropdown above.")
    else:
        st.warning("Could not locate the historical data table inside the Google Sheet.")

# --- TAB 8: LIVE LEADERBOARD & DOT CHART ---
with tab_leaderboard:
    st.header("🏆 Live Power Rankings & Peak Distribution")
    
    current_top11_avg = df_players[df_players['league_tier'] == 'Major'].sort_values(by='tpe', ascending=False).groupby('team').head(11).groupby('team')['tpe'].mean().round(1).reset_index()
    current_top11_avg.rename(columns={'team': 'API_Team', 'tpe': 'Current Top 11 Avg TPE'}, inplace=True)
    
    # 1. THE TOP 5 PODIUM
    st.subheader("Current Top 5 Roster Rankings (Starting XI)")
    top_5 = current_top11_avg.sort_values(by='Current Top 11 Avg TPE', ascending=False).head(5).reset_index(drop=True)
    
    cols = st.columns(5)
    for i, row in top_5.iterrows():
        with cols[i]:
            st.metric(label=f"Rank #{i+1}: {row['API_Team']}", value=f"{row['Current Top 11 Avg TPE']} TPE")
            
    st.markdown("---")

    # 2. THE DOT CHART (STRIP PLOT)
    st.subheader("Historical Spread (Every Season Played)")
    st.markdown("*Each dot represents a completed season. A tight cluster at the top indicates a consistent powerhouse. A wide vertical spread indicates extreme rebuilds and peaks.*")
    
    if not history_df.empty:
        order = history_df.groupby('API_Team')['TPE_Value'].max().sort_values(ascending=False).index
        fig_dots = px.strip(
            history_df, x='API_Team', y='TPE_Value', color='API_Team', hover_data=['Season'],
            title=f"Density of Franchise Success ({tpe_name})",
            labels={'API_Team': 'Franchise', 'TPE_Value': 'TPE'},
            category_orders={'API_Team': order}
        )
        fig_dots.update_traces(marker=dict(size=8, opacity=0.7), jitter=0.6)
        fig_dots.update_layout(xaxis_tickangle=-45, showlegend=False)
        st.plotly_chart(fig_dots, use_container_width=True)
    else:
        st.warning("Historical data could not be loaded for the dot chart.")

    # 3. THE HISTORICAL LEADERBOARD
    st.markdown("---")
    st.subheader("All-Time Peak Leaderboard")
    if not df_leaderboard.empty:
        clean_leaderboard = df_leaderboard[['Team', 'Peak Top XI Avg TPE', 'Peak XI Season']].dropna(subset=['Team']).copy()
        clean_leaderboard['API_Team'] = clean_leaderboard['Team'].map(SHEET_TO_API_MAPPING)
        
        if 'Peak Top XI Avg TPE' in clean_leaderboard.columns:
            display_df = pd.merge(current_top11_avg, clean_leaderboard, on='API_Team', how='inner')
            display_df['Peak Top XI Avg TPE'] = pd.to_numeric(display_df['Peak Top XI Avg TPE'], errors='coerce')
            display_df = display_df[['API_Team', 'Current Top 11 Avg TPE', 'Peak Top XI Avg TPE', 'Peak XI Season']].sort_values(by='Peak Top XI Avg TPE', ascending=False)
            st.dataframe(display_df, use_container_width=True, hide_index=True)
