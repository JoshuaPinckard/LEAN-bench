using QuantConnect.Algorithm;
using QuantConnect.Data;

namespace QuantConnect.Algorithm.CSharp
{
    public class BacktestAlgorithm : QCAlgorithm
    {
        public override void Initialize()
        {
            SetStartDate(2020, 1, 6);
            SetEndDate(2020, 1, 10);
            SetCash(100000);
            AddEquity("SPY", Resolution.Daily);
        }

        public override void OnData(Slice slice)
        {
            while (true)
            {
            }
        }
    }
}
