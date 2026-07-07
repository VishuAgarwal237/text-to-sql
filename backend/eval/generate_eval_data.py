import json
from utils import load_db, query_db
import os

def test_query(conn, sql, description):
    """Test a SQL query and return the results if valid."""
    try:
        result = query_db(conn, sql, return_as_df=True)
        print(f"✓ {description}")
        print(f"  Returned {len(result)} rows")
        result_list = result.to_dict("records")
        return True, result_list
    except Exception as e:
        print(f"✗ {description}")
        print(f"  Error: {e}")
        return False, None


def main():
    # Load database
    conn = load_db()
    print("Database loaded successfully!\n")

    test_cases = [
        {
            "question": "What are the top 5 best-selling genres by total sales?",
            "sql": "SELECT g.Name, SUM(il.UnitPrice * il.Quantity) as TotalSales FROM Genre g JOIN Track t ON g.GenreId = t.GenreId JOIN InvoiceLine il ON t.TrackId = il.TrackId GROUP BY g.Name ORDER BY TotalSales DESC LIMIT 5",
            "category": "aggregation_with_joins",
        },
        {
            "question": "How many customers does each country have?",
            "sql": "SELECT Country, COUNT(*) as CustomerCount FROM Customer GROUP BY Country ORDER BY CustomerCount DESC",
            "category": "simple_aggregation",
        },
        {
            "question": "Which employee has the most customers assigned to them?",
            "sql": "SELECT e.FirstName || ' ' || e.LastName as EmployeeName, COUNT(c.CustomerId) as CustomerCount FROM Employee e JOIN Customer c ON e.EmployeeId = c.SupportRepId GROUP BY e.EmployeeId, e.FirstName, e.LastName ORDER BY CustomerCount DESC LIMIT 1",
            "category": "aggregation_with_joins",
        },
        {
            "question": "What is the average invoice total for each country?",
            "sql": "SELECT BillingCountry, AVG(Total) as AverageInvoiceTotal FROM Invoice GROUP BY BillingCountry ORDER BY AverageInvoiceTotal DESC",
            "category": "simple_aggregation",
        },
        {
            "question": "List all albums by the artist 'AC/DC'",
            "sql": "SELECT al.Title FROM Album al JOIN Artist ar ON al.ArtistId = ar.ArtistId WHERE ar.Name = 'AC/DC'",
            "category": "filtering_with_join",
        },
        {
            "question": "What are the names and email addresses of customers from Brazil?",
            "sql": "SELECT FirstName, LastName, Email FROM Customer WHERE Country = 'Brazil'",
            "category": "simple_filtering",
        },
        {
            "question": "How many tracks are there in each playlist?",
            "sql": "SELECT p.Name, COUNT(pt.TrackId) as TrackCount FROM Playlist p LEFT JOIN PlaylistTrack pt ON p.PlaylistId = pt.PlaylistId GROUP BY p.PlaylistId, p.Name ORDER BY TrackCount DESC",
            "category": "aggregation_with_joins",
        },
        {
            "question": "What is the total revenue generated in the year 2021?",
            "sql": "SELECT SUM(Total) as TotalRevenue FROM Invoice WHERE strftime('%Y', InvoiceDate) = '2021'",
            "category": "date_filtering",
        },
        {
            "question": "Which 5 tracks have the longest duration?",
            "sql": "SELECT Name, Milliseconds FROM Track ORDER BY Milliseconds DESC LIMIT 5",
            "category": "simple_sorting",
        },
        {
            "question": "What is the most popular media type based on number of tracks?",
            "sql": "SELECT mt.Name, COUNT(t.TrackId) as TrackCount FROM MediaType mt JOIN Track t ON mt.MediaTypeId = t.MediaTypeId GROUP BY mt.MediaTypeId, mt.Name ORDER BY TrackCount DESC LIMIT 1",
            "category": "aggregation_with_joins",
        },
    ]

    print("Testing SQL queries...\n")
    print("=" * 80)

    valid_cases = []
    for i, test_case in enumerate(test_cases, 1):
        print(f"\n{i}. {test_case['question']}")
        success, results = test_query(conn, test_case["sql"], f"Query {i}")
        if success:
            valid_cases.append(
                {
                    "question": test_case["question"],
                    "sql": test_case["sql"],
                    "expected_result": results,
                }
            )

    print("\n" + "=" * 80)
    print(f"\nValidated {len(valid_cases)}/{len(test_cases)} queries successfully!")
    cwd = os.getcwd()

    output_file = cwd + "/evaluation_data.json"
    with open(output_file, "w") as f:
        json.dump(valid_cases, f, indent=2)

    print(f"\nEvaluation data saved to {output_file}")
    print(f"Each test case includes the expected query results for validation.")

    conn.close()


if __name__ == "__main__":
    main()
