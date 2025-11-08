import pandas as pd

#Q1
df = pd.read_csv("matches.csv")
# total number of matches
tot_matches = df.size
print(tot_matches)
# column names
col_names = df.columns
print(col_names)
# First 5 rows of data
first_five = df.head()
print(first_five)
# describe data
desc = df.describe()
print(desc)

#Q2
# Matches decided by 1 run or 1 wicket
final_ball_games = df[(df['win_by_runs'] == 1) | (df['win_by_wickets'] == 1)]
top_player = (final_ball_games['player_of_match'].value_counts().idxmax())

print(top_player)

#Q3
wankhede = df[df['venue'].str.contains("Wankhede", case=False, na=False)]
bat_first_wins = len(wankhede[wankhede['win_by_runs'] > 0])
bat_second_wins = len(wankhede[wankhede['win_by_wickets'] > 0])
print("\nQ3. At Wankhede Stadium:")
print(f" - Batting first wins (by runs): {bat_first_wins}")
print(f" - Batting second wins (by wickets): {bat_second_wins}")
if bat_first_wins > bat_second_wins:
    print("More common to win by batting first.")
else:
    print("More common to win by batting second.")

#Q4
big_wins = df[df['win_by_runs'] > 50]
team_with_most_big_wins = big_wins['winner'].value_counts().idxmax()
print("\n Team with highest number of wins (>50 runs):", team_with_most_big_wins)

#Q5
toss_winners = df['toss_winner']
dec = toss_winners['toss_decision'].eq('bat')
winner_overall = dec['winner']
print(winner_overall.sum())

#Q6
kkr_matches = df[(df['team1'].str.contains("Kolkata Knight Riders", case=False, na=False)) | (df['team2'].str.contains("Kolkata Knight Riders", case=False, na=False))]
umpire1_count = kkr_matches['umpire1'].value_counts().sum()
umpire2_count = kkr_matches['umpire2'].value_counts().sum()
umpire_counts = pd.concat([kkr_matches['umpire1'], kkr_matches['umpire2']]).value_counts()
top_umpire = umpire_counts.idxmax()
print("Umpire who officiated most KKR matches:", top_umpire)